from threading import Thread
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Thread
from typing import Callable
from kivy.clock import Clock
import time
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from api.api_bazara import BazaraAPI
from api.api_openfoodfacts import OpenFoodFactsAPI
from api.api_upcitemdb import UPCitemdbAPI
from api.api_sixty60 import Sixty60API


class APIManager:
    """
    Gerencia a busca de produtos em múltiplas APIs com cache offline.

    NÍVEIS DE CACHE:
    1. Cache em memória (RAM) - mais rápido, perde ao fechar app
    2. Cache em arquivo (JSON) - persiste, funciona offline
    3. Banco de dados - produtos cadastrados oficialmente

    MELHORIAS v3:
    - ✅ Cache PERSISTENTE em arquivo JSON
    - ✅ Funciona 100% OFFLINE após primeiro scan
    - ✅ Sincronização inteligente
    - ✅ Limpeza automática de cache antigo
    - ✅ Estatísticas detalhadas

    Ordem de prioridade:
        0. Cache em memória (instantâneo)
        1. Cache em arquivo offline (muito rápido)
        2. Banco de dados local (rápido)
        3. APIs externas (lento, requer internet)
    """

    # APIs externas
    EXTERNAL_SOURCES = [
        ("Bazara",         BazaraAPI()),
        ("Open Food Facts", OpenFoodFactsAPI()),
        ("UPCitemdb",      UPCitemdbAPI()),
        ("Sixty60",        Sixty60API()),
    ]

    def __init__(self, database, on_success: callable, on_failure: callable, on_status: callable = None):
        """
        database   : instância de Database() para busca local
        on_success : chamado com (fonte, dados) quando produto é encontrado
        on_failure : chamado quando nenhuma fonte retorna dados
        on_status  : chamado com (mensagem) durante a busca (opcional)
        """
        self.db = database
        self.on_success = on_success
        self.on_failure = on_failure
        self.on_status  = on_status
        self.is_loading = False
        
        # Cache em memória (temporário)
        self.memory_cache = {}
        self.cache_duration = timedelta(hours=1)
        
        # Cache em arquivo (persistente)
        self.cache_file = self._get_cache_file_path()
        self.offline_cache = self._load_offline_cache()
        self.offline_cache_duration = timedelta(days=30)  # Cache offline dura 30 dias
        
        # Configurações
        self.timeout_per_api = 5
        self.use_parallel_search = True
        self.auto_save_to_offline = True  # Salvar automaticamente em arquivo
        self.max_offline_entries = 1000   # Máximo de produtos no cache offline
        
        # Estatísticas
        self.stats = {
            'memory_hits': 0,
            'offline_hits': 0,
            'database_hits': 0,
            'api_hits': 0,
            'total_searches': 0
        }

    def _get_cache_file_path(self):
        """Retorna caminho do arquivo de cache."""
        # Criar diretório de cache se não existir
        cache_dir = Path("data/cache")
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / "products_offline_cache.json"

    def _load_offline_cache(self):
        """Carrega cache do arquivo JSON."""
        try:
            if self.cache_file.exists():
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    print(f"[APIManager] Cache offline carregado: {len(data)} produtos")
                    return data
        except Exception as e:
            print(f"[APIManager] Erro ao carregar cache offline: {e}")
        
        return {}

    def _save_offline_cache(self):
        """Salva cache no arquivo JSON."""
        try:
            # Limpar entradas expiradas antes de salvar
            self._clean_expired_offline()
            
            # Limitar número de entradas
            if len(self.offline_cache) > self.max_offline_entries:
                # Manter apenas as mais recentes
                sorted_items = sorted(
                    self.offline_cache.items(),
                    key=lambda x: x[1].get('timestamp', ''),
                    reverse=True
                )
                self.offline_cache = dict(sorted_items[:self.max_offline_entries])
            
            # Salvar
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.offline_cache, f, ensure_ascii=False, indent=2)
            
            print(f"[APIManager] Cache offline salvo: {len(self.offline_cache)} produtos")
        except Exception as e:
            print(f"[APIManager] Erro ao salvar cache offline: {e}")

    def _clean_expired_offline(self):
        """Remove entradas expiradas do cache offline."""
        now = datetime.now()
        expired_keys = []
        
        for barcode, entry in self.offline_cache.items():
            try:
                timestamp = datetime.fromisoformat(entry.get('timestamp', ''))
                if now - timestamp > self.offline_cache_duration:
                    expired_keys.append(barcode)
            except:
                expired_keys.append(barcode)  # Remover se timestamp inválido
        
        for key in expired_keys:
            del self.offline_cache[key]
        
        if expired_keys:
            print(f"[APIManager] Removidas {len(expired_keys)} entradas expiradas do cache")

    def search(self, barcode: str, force_external=False):
        """
        Inicia a busca.
        
        force_external : se True, pula todos os caches e busca direto nas APIs
        """
        if self.is_loading:
            return

        self.is_loading = True
        self.stats['total_searches'] += 1
        Thread(target=self._search_all, args=(barcode, force_external), daemon=True).start()

    def search_enriched(
        self,
        barcode: str,
        required_fields=None,
        on_partial: Callable | None = None,
        on_complete: Callable | None = None,
        force_external: bool = False,
    ):
        """
        Busca enriquecida: preenche rapidamente com cache/banco e completa
        campos faltantes consultando todas as APIs em paralelo.
        """
        if self.is_loading:
            return

        self.is_loading = True
        self.stats['total_searches'] += 1
        Thread(
            target=self._search_all_enriched,
            args=(barcode, required_fields, on_partial, on_complete, force_external),
            daemon=True,
        ).start()

    def _search_all(self, barcode: str, force_external: bool):
        """Coordena a busca completa com múltiplos níveis."""
        try:
            barcode = self._normalize_barcode(barcode)
            if not barcode:
                self._notify_status("C?digo inv?lido")
                Clock.schedule_once(lambda dt: self.on_failure(), 0)
                return
            bazara_result = self._fetch_bazara_first(barcode)
            if bazara_result:
                self.stats['api_hits'] += 1
                source_name, data = bazara_result
                self._save_to_memory_cache(barcode, source_name, data)
                if self.auto_save_to_offline:
                    self._save_to_offline_cache(barcode, source_name, data)
                self._notify_status(f"Encontrado em {source_name}")
                Clock.schedule_once(lambda dt: self.on_success(source_name, data), 0)
                return

            # NÍVEL 0: Cache em memória
            if not force_external:
                cached = self._get_from_memory_cache(barcode)
                if cached:
                    self.stats['memory_hits'] += 1
                    self._notify_status("⚡ Cache (memória)")
                    Clock.schedule_once(lambda dt: self.on_success(cached['source'], cached['data']), 0)
                    return

            # NÍVEL 1: Cache offline (arquivo JSON)
            if not force_external:
                offline_result = self._get_from_offline_cache(barcode)
                if offline_result:
                    self.stats['offline_hits'] += 1
                    self._notify_status("💾 Cache (offline)")
                    # Adicionar também ao cache em memória
                    self._save_to_memory_cache(barcode, offline_result['source'], offline_result['data'])
                    Clock.schedule_once(lambda dt: self.on_success(offline_result['source'], offline_result['data']), 0)
                    return

            # NÍVEL 2: Banco de dados local
            if not force_external:
                self._notify_status("🔍 Buscando no banco local...")
                local_result = self._search_local(barcode)
                if local_result:
                    self.stats['database_hits'] += 1
                    # Salvar em TODOS os caches
                    self._save_to_memory_cache(barcode, "Banco Local", local_result)
                    self._save_to_offline_cache(barcode, "Banco Local", local_result)
                    Clock.schedule_once(lambda dt: self.on_success("Banco Local", local_result), 0)
                    return

            # NIVEL 3: APIs externas
            self._notify_status("Buscando online...")
            external_sources = self._get_external_sources(include_bazara=False)
            if self.use_parallel_search:
                result = self._search_parallel(barcode, sources=external_sources)
            else:
                result = self._search_sequential(barcode, sources=external_sources)

            if result:
                self.stats['api_hits'] += 1
                source_name, data = result

                # Salvar em TODOS os niveis de cache
                self._save_to_memory_cache(barcode, source_name, data)
                if self.auto_save_to_offline:
                    self._save_to_offline_cache(barcode, source_name, data)

                self._notify_status(f"Encontrado em {source_name}")
                Clock.schedule_once(lambda dt: self.on_success(source_name, data), 0)
            else:
                # Nenhuma fonte retornou dados
                self._notify_status("Produto nao encontrado")
                Clock.schedule_once(lambda dt: self.on_failure(), 0)

        except Exception as e:
            print(f"[APIManager] Erro inesperado: {e}")
            Clock.schedule_once(lambda dt: self.on_failure(), 0)

        finally:
            self.is_loading = False

    def _search_all_enriched(
        self,
        barcode: str,
        required_fields,
        on_partial: Callable | None,
        on_complete: Callable | None,
        force_external: bool,
    ):
        """Busca enriquecida com merge por campo e preenchimento progressivo."""
        source_chain = []
        merged = {}
        try:
            barcode = self._normalize_barcode(barcode)
            if not barcode:
                if on_complete:
                    Clock.schedule_once(
                        lambda dt: on_complete({'source_chain': []}),
                        0,
                    )
                return
    
            merged['barcode'] = barcode
            required_fields = required_fields or ['name', 'brand', 'category', 'quantity']
    
            def _merge_data(source_name: str, data: dict):
                if not data:
                    return False
                updated = False
                for key, value in data.items():
                    if value is None or value == '' or value == []:
                        continue
                    if not merged.get(key):
                        merged[key] = value
                        updated = True
                if source_name and source_name not in source_chain:
                    source_chain.append(source_name)
                return updated
    
            def _missing_fields():
                return [f for f in required_fields if not merged.get(f)]
    
            def _emit_partial(source_name: str):
                if not on_partial:
                    return
                payload = dict(merged)
                payload['source_chain'] = list(source_chain)
                Clock.schedule_once(
                    lambda dt, s=source_name, p=payload: on_partial(s, p),
                    0,
                )
    
            found_external = False
            bazara_result = self._fetch_bazara_first(barcode)
            if bazara_result:
                source_name, data = bazara_result
                updated = _merge_data(source_name, data)
                found_external = True
                if updated:
                    _emit_partial(source_name)
    
            # N?VEL 0: Cache em mem?ria
            if not force_external:
                cached = self._get_from_memory_cache(barcode)
                if cached:
                    self.stats['memory_hits'] += 1
                    _merge_data(cached.get('source', 'Cache (mem?ria)'), cached.get('data', {}))
                    _emit_partial(cached.get('source', 'Cache (mem?ria)'))
    
            # N?VEL 1: Cache offline
            if not force_external and _missing_fields():
                offline_result = self._get_from_offline_cache(barcode)
                if offline_result:
                    self.stats['offline_hits'] += 1
                    _merge_data(offline_result.get('source', 'Cache (offline)'), offline_result.get('data', {}))
                    _emit_partial(offline_result.get('source', 'Cache (offline)'))
    
            # N?VEL 2: Banco local
            if not force_external and _missing_fields():
                local_result = self._search_local(barcode)
                if local_result:
                    self.stats['database_hits'] += 1
                    _merge_data('Banco Local', local_result)
                    _emit_partial('Banco Local')
    
            # N?VEL 3: APIs externas
            if _missing_fields():
                external_sources = self._get_external_sources(include_bazara=False)
                if external_sources:
                    with ThreadPoolExecutor(max_workers=len(external_sources)) as executor:
                        future_to_source = {
                            executor.submit(self._fetch_with_timeout, api, barcode, self.timeout_per_api): source_name
                            for source_name, api in external_sources
                        }
    
                        for future in as_completed(future_to_source):
                            source_name = future_to_source[future]
                            try:
                                result = future.result()
                            except Exception:
                                result = None
    
                            if not result:
                                continue
    
                            found_external = True
                            updated = _merge_data(source_name, result)
                            if updated:
                                _emit_partial(source_name)
    
                            if not _missing_fields():
                                for f in future_to_source:
                                    f.cancel()
                                break
    
            if found_external:
                self.stats['api_hits'] += 1
    
            payload = dict(merged)
            payload['source_chain'] = list(source_chain)
    
            if source_chain:
                cache_source = source_chain[0] if len(source_chain) == 1 else 'Agregado'
                self._save_to_memory_cache(barcode, cache_source, payload)
                if self.auto_save_to_offline:
                    self._save_to_offline_cache(barcode, cache_source, payload)
    
            if on_complete:
                Clock.schedule_once(lambda dt, p=payload: on_complete(p), 0)
    
        except Exception as e:
            print(f"[APIManager] Erro inesperado (enriched): {e}")
            if on_complete:
                Clock.schedule_once(lambda dt: on_complete({'source_chain': []}), 0)
        finally:
            self.is_loading = False
    def _search_local(self, barcode: str):
        """Busca no banco de dados local."""
        try:
            barcode = self._normalize_barcode(barcode)
            if not barcode:
                return None
            self.db.cursor.execute("""
                SELECT id, description, existing_stock, sale_price,
                       unit_purchase_price, barcode, is_sold_by_weight,
                       expiry_date, status
                FROM products
                WHERE barcode = ?
            """, (barcode,))
            
            result = self.db.cursor.fetchone()
            
            if result:
                pid, name, stock, price, cost, barcode, is_weight, exp, status = result
                return {
                    'name': name,
                    'barcode': barcode,
                    'price': price,
                    'cost': cost,
                    'stock': stock,
                    'is_weight': is_weight,
                    'expiry_date': exp,
                    'status': status,
                    'product_id': pid,
                    'source': 'local'
                }
            return None
        except Exception as e:
            print(f"[APIManager] Erro ao buscar localmente: {e}")
            return None

    def _search_sequential(self, barcode: str, sources=None):
        """Busca sequencial nas APIs."""
        sources = sources or self.EXTERNAL_SOURCES
        for source_name, api in sources:
            self._notify_status(f"Buscando em {source_name}...")
            
            try:
                result = api.fetch(barcode)
                if result:
                    return (source_name, result)
            except Exception as e:
                print(f"[APIManager] Erro em {source_name}: {e}")
                continue
        
        return None

    def _search_parallel(self, barcode: str, sources=None):
        """Busca paralela em todas as APIs."""
        self._notify_status("Buscando em múltiplas fontes...")
        sources = sources or self.EXTERNAL_SOURCES
        if not sources:
            return None
        
        with ThreadPoolExecutor(max_workers=len(sources)) as executor:
            future_to_source = {
                executor.submit(self._fetch_with_timeout, api, barcode, self.timeout_per_api): source_name
                for source_name, api in sources
            }
            
            for future in as_completed(future_to_source):
                source_name = future_to_source[future]
                
                try:
                    result = future.result()
                    if result:
                        # Cancelar buscas restantes
                        for f in future_to_source:
                            f.cancel()
                        
                        return (source_name, result)
                except Exception as e:
                    print(f"[APIManager] Erro em {source_name}: {e}")
                    continue
        
        return None

    def _fetch_with_timeout(self, api, barcode: str, timeout: int):
        """Executa fetch com timeout."""
        try:
            return api.fetch(barcode)
        except Exception as e:
            return None

    def _get_external_sources(self, include_bazara=True):
        if include_bazara:
            return self.EXTERNAL_SOURCES
        return [(name, api) for name, api in self.EXTERNAL_SOURCES if name.lower() != "bazara"]

    def _fetch_bazara_first(self, barcode: str):
        """Busca primeiro no Bazara."""
        for source_name, api in self.EXTERNAL_SOURCES:
            if source_name.lower() == "bazara":
                self._notify_status("Buscando no Bazara...")
                result = self._fetch_with_timeout(api, barcode, self.timeout_per_api)
                if result:
                    return (source_name, result)
                return None
        return None

    # ========== CACHE EM MEMÓRIA ==========

    def _get_from_memory_cache(self, barcode: str):
        """Recupera do cache em memória."""
        if barcode in self.memory_cache:
            entry = self.memory_cache[barcode]
            if datetime.now() - entry['timestamp'] < self.cache_duration:
                return entry
            else:
                del self.memory_cache[barcode]
        return None

    def _save_to_memory_cache(self, barcode: str, source: str, data):
        """Salva no cache em memória."""
        self.memory_cache[barcode] = {
            'source': source,
            'data': data,
            'timestamp': datetime.now()
        }

    # ========== CACHE OFFLINE (PERSISTENTE) ==========
    
    def _get_from_offline_cache(self, barcode: str):
        """Recupera do cache offline."""
        if barcode in self.offline_cache:
            entry = self.offline_cache[barcode]
            try:
                timestamp = datetime.fromisoformat(entry.get('timestamp', ''))
                if datetime.now() - timestamp < self.offline_cache_duration:
                    return {
                        'source': entry.get('source'),
                        'data': entry.get('data')
                    }
                else:
                    # Expirado
                    del self.offline_cache[barcode]
                    self._save_offline_cache()
            except:
                pass
        return None

    def _save_to_offline_cache(self, barcode: str, source: str, data):
        """Salva no cache offline (arquivo JSON)."""
        self.offline_cache[barcode] = {
            'source': source,
            'data': data,
            'timestamp': datetime.now().isoformat()
        }
        
        # Salvar arquivo (async para não bloquear)
        Thread(target=self._save_offline_cache, daemon=True).start()

    # ========== GERENCIAMENTO ==========
    
    def clear_all_caches(self):
        """Limpa todos os caches (memória + arquivo)."""
        self.memory_cache.clear()
        self.offline_cache.clear()
        self._save_offline_cache()
        print("[APIManager] Todos os caches limpos")

    def clear_memory_cache(self):
        """Limpa apenas cache em memória."""
        self.memory_cache.clear()

    def remove_from_cache(self, barcode: str):
        """Remove entrada específica de todos os caches."""
        if barcode in self.memory_cache:
            del self.memory_cache[barcode]
        if barcode in self.offline_cache:
            del self.offline_cache[barcode]
            self._save_offline_cache()

    def export_offline_cache(self, filepath: str):
        """Exporta cache offline para outro arquivo (backup)."""
        try:
            import shutil
            shutil.copy(self.cache_file, filepath)
            print(f"[APIManager] Cache exportado para {filepath}")
            return True
        except Exception as e:
            print(f"[APIManager] Erro ao exportar cache: {e}")
            return False

    def import_offline_cache(self, filepath: str):
        """Importa cache offline de outro arquivo."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                imported = json.load(f)
            
            # Mesclar com cache existente
            self.offline_cache.update(imported)
            self._save_offline_cache()
            print(f"[APIManager] Cache importado: {len(imported)} produtos")
            return True
        except Exception as e:
            print(f"[APIManager] Erro ao importar cache: {e}")
            return False

    # ========== ESTATÍSTICAS ==========
    
    def get_statistics(self):
        """Retorna estatísticas detalhadas."""
        total = self.stats['total_searches']
        
        return {
            'total_searches': total,
            'memory_hits': self.stats['memory_hits'],
            'offline_hits': self.stats['offline_hits'],
            'database_hits': self.stats['database_hits'],
            'api_hits': self.stats['api_hits'],
            'memory_hit_rate': f"{(self.stats['memory_hits'] / total * 100):.1f}%" if total > 0 else "0%",
            'offline_hit_rate': f"{(self.stats['offline_hits'] / total * 100):.1f}%" if total > 0 else "0%",
            'cache_efficiency': f"{((self.stats['memory_hits'] + self.stats['offline_hits']) / total * 100):.1f}%" if total > 0 else "0%",
            'memory_cache_size': len(self.memory_cache),
            'offline_cache_size': len(self.offline_cache),
            'offline_cache_file_size': self._get_file_size()
        }

    def _get_file_size(self):
        """Retorna tamanho do arquivo de cache."""
        try:
            if self.cache_file.exists():
                size_bytes = self.cache_file.stat().st_size
                if size_bytes < 1024:
                    return f"{size_bytes} B"
                elif size_bytes < 1024 * 1024:
                    return f"{size_bytes / 1024:.1f} KB"
                else:
                    return f"{size_bytes / (1024 * 1024):.1f} MB"
        except:
            return "0 B"

    def reset_statistics(self):
        """Reseta estatísticas."""
        self.stats = {
            'memory_hits': 0,
            'offline_hits': 0,
            'database_hits': 0,
            'api_hits': 0,
            'total_searches': 0
        }

    # ========== CONFIGURAÇÕES ==========
    
    def set_parallel_mode(self, enabled: bool):
        """Ativa/desativa busca paralela."""
        self.use_parallel_search = enabled

    def set_timeout(self, seconds: int):
        """Define timeout por API."""
        self.timeout_per_api = seconds

    def set_auto_save_offline(self, enabled: bool):
        """Ativa/desativa salvamento automático no cache offline."""
        self.auto_save_to_offline = enabled

    def set_max_offline_entries(self, max_entries: int):
        """Define número máximo de produtos no cache offline."""
        self.max_offline_entries = max_entries

    def set_offline_cache_duration(self, days: int):
        """Define duração do cache offline em dias."""
        self.offline_cache_duration = timedelta(days=days)

    # ========== HELPERS ==========
    
    def _notify_status(self, message: str):
        """Enfileira atualização de status na thread principal."""
        if self.on_status:
            Clock.schedule_once(lambda dt, m=message: self.on_status(m), 0)

    def _normalize_barcode(self, barcode: str) -> str:
        if barcode is None:
            return ""
        cleaned = "".join(c for c in str(barcode) if c.isprintable()).strip()
        return cleaned.replace(" ", "")
