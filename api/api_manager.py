from threading import Thread
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Thread
from typing import Callable
from kivy.clock import Clock
import time
import json
import os
import requests
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET
from bs4 import BeautifulSoup

from api.api_bazara import BazaraAPI
from api.api_openfoodfacts import OpenFoodFactsAPI
from api.api_ranxo import RanxoAPI
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
        ("Ranxo",          RanxoAPI()),
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

        # Cache separado para Open Food Facts
        self.openfoodfacts_cache_file = self._get_openfoodfacts_cache_file_path()
        self.openfoodfacts_cache = self._load_openfoodfacts_cache()
        
        # Configurações
        self.timeout_per_api = 5
        # Sequencial para dar feedback claro de cada API no status.
        self.use_parallel_search = False
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

    def _get_openfoodfacts_cache_file_path(self):
        """Retorna caminho do arquivo de cache do Open Food Facts."""
        cache_dir = Path("data/cache")
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir / "openfoodfacts_cache.json"

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

    def _load_openfoodfacts_cache(self):
        """Carrega cache do Open Food Facts do arquivo JSON."""
        try:
            if self.openfoodfacts_cache_file.exists():
                with open(self.openfoodfacts_cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    print(f"[APIManager] Cache Open Food Facts carregado: {len(data)} produtos")
                    return data
        except Exception as e:
            print(f"[APIManager] Erro ao carregar cache Open Food Facts: {e}")
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

    def _save_openfoodfacts_cache(self):
        """Salva cache do Open Food Facts no arquivo JSON."""
        try:
            with open(self.openfoodfacts_cache_file, 'w', encoding='utf-8') as f:
                json.dump(self.openfoodfacts_cache, f, ensure_ascii=False, indent=2)
            print(f"[APIManager] Cache Open Food Facts salvo: {len(self.openfoodfacts_cache)} produtos")
        except Exception as e:
            print(f"[APIManager] Erro ao salvar cache Open Food Facts: {e}")

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
                self._notify_status("Código inválido")
                Clock.schedule_once(lambda dt: self.on_failure(), 0)
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
            external_sources = self._get_external_sources(include_bazara=True)
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
    
            # NÍVEL 0: Cache em memória
            if not force_external:
                cached = self._get_from_memory_cache(barcode)
                if cached:
                    self.stats['memory_hits'] += 1
                    _merge_data(cached.get('source', 'Cache (memória)'), cached.get('data', {}))
                    _emit_partial(cached.get('source', 'Cache (memória)'))
    
            # NÍVEL 1: Cache offline
            if not force_external and _missing_fields():
                offline_result = self._get_from_offline_cache(barcode)
                if offline_result:
                    self.stats['offline_hits'] += 1
                    _merge_data(offline_result.get('source', 'Cache (offline)'), offline_result.get('data', {}))
                    _emit_partial(offline_result.get('source', 'Cache (offline)'))
    
            # NÍVEL 2: Banco local
            if not force_external and _missing_fields():
                local_result = self._search_local(barcode)
                if local_result:
                    self.stats['database_hits'] += 1
                    _merge_data('Banco Local', local_result)
                    _emit_partial('Banco Local')
    
            # NÍVEL 3: APIs externas
            if _missing_fields():
                external_sources = self._get_external_sources(include_bazara=True)
                if external_sources:
                    if self.use_parallel_search:
                        self._notify_status("Buscando em múltiplas fontes...")
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
                    else:
                        for source_name, api in external_sources:
                            if not _missing_fields():
                                break
                            self._notify_status(f"Buscando em {source_name}...")
                            result = self._fetch_with_timeout(api, barcode, self.timeout_per_api)
                            if not result:
                                self._notify_status(f"Sem resultado em {source_name}.")
                                continue
                            found_external = True
                            updated = _merge_data(source_name, result)
                            if updated:
                                _emit_partial(source_name)
    
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
            result = self.db.get_product_by_barcode(barcode)
            if result:
                pid = result[0]
                full = self.db.get_product(pid)
                if full:
                    return {
                        'name': full[1],
                        'barcode': full[12],
                        'price': full[4],
                        'cost': full[6],
                        'stock': full[2],
                        'is_weight': full[15],
                        'sold_by_weight': bool(full[15]),
                        'expiry_date': full[13],
                        'status': full[16],
                        'category': full[11],
                        'quantity': full[21],
                        'product_id': full[0],
                        'source': 'local'
                    }
                pid, name, stock, price, barcode_val, is_weight = result
                return {
                    'name': name,
                    'barcode': barcode_val,
                    'price': price,
                    'stock': stock,
                    'is_weight': is_weight,
                    'sold_by_weight': bool(is_weight),
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
                self._notify_status(f"Sem resultado em {source_name}.")
            except Exception as e:
                print(f"[APIManager] Erro em {source_name}: {e}")
                self._notify_status(f"Erro em {source_name}.")
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
        if isinstance(data, dict) and not data.get("barcode"):
            data = dict(data)
            data["barcode"] = barcode
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

    @staticmethod
    def _is_openfoodfacts_source(source: str, data: dict | None) -> bool:
        if source and "open food facts" in source.lower():
            return True
        if isinstance(data, dict):
            chain = data.get("source_chain")
            if isinstance(chain, list):
                for item in chain:
                    if isinstance(item, str) and "open food facts" in item.lower():
                        return True
        return False

    def _save_to_openfoodfacts_cache(self, barcode: str, data: dict):
        payload = dict(data) if isinstance(data, dict) else {}
        if not payload.get("barcode"):
            payload["barcode"] = barcode
        self.openfoodfacts_cache[barcode] = {
            "source": "Open Food Facts",
            "data": payload,
            "timestamp": datetime.now().isoformat(),
        }
        Thread(target=self._save_openfoodfacts_cache, daemon=True).start()

    def _upsert_openfoodfacts_cache(self, barcode: str, data: dict):
        payload = dict(data) if isinstance(data, dict) else {}
        if not payload.get("barcode"):
            payload["barcode"] = barcode
        self.openfoodfacts_cache[barcode] = {
            "source": "Open Food Facts",
            "data": payload,
            "timestamp": datetime.now().isoformat(),
        }

    def _save_to_offline_cache(self, barcode: str, source: str, data):
        """Salva no cache offline (arquivo JSON)."""
        if isinstance(data, dict) and not data.get("barcode"):
            data = dict(data)
            data["barcode"] = barcode
        self.offline_cache[barcode] = {
            'source': source,
            'data': data,
            'timestamp': datetime.now().isoformat()
        }
        
        # Salvar arquivo (async para não bloquear)
        Thread(target=self._save_offline_cache, daemon=True).start()
        if self._is_openfoodfacts_source(source, data):
            self._save_to_openfoodfacts_cache(barcode, data)

    # ========== GERENCIAMENTO ==========
    
    def clear_all_caches(self):
        """Limpa todos os caches (memória + arquivo)."""
        self.memory_cache.clear()
        self.offline_cache.clear()
        self._save_offline_cache()
        self.openfoodfacts_cache.clear()
        self._save_openfoodfacts_cache()
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
        if barcode in self.openfoodfacts_cache:
            del self.openfoodfacts_cache[barcode]
            self._save_openfoodfacts_cache()

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

    # ========== RANXO PREFILL ==========

    def prefill_ranxo_cache(self, on_progress=None, delay: float = 0.2):
        """
        Prefill do cache offline usando sitemap do Ranxo.
        Executa em modo sequencial e salva uma unica vez no final.
        """
        stats = {
            "total": 0,
            "processed": 0,
            "success": 0,
            "new": 0,
            "no_sku": 0,
            "errors": 0,
        }
        original_max = self.max_offline_entries
        session = requests.Session()
        session.headers.update(getattr(RanxoAPI, "HEADERS", {}))
        timeout = getattr(RanxoAPI, "REQUEST_TIMEOUT", 6)

        try:
            sitemap_urls = self._ranxo_get_sitemap_urls(session, timeout)
            product_urls = self._ranxo_get_product_urls(session, sitemap_urls, timeout)
            stats["total"] = len(product_urls)

            if stats["total"] > self.max_offline_entries:
                self.max_offline_entries = stats["total"]

            self._emit_prefill_progress(on_progress, stats, "Iniciando prefill Ranxo...")

            for idx, url in enumerate(product_urls, 1):
                stats["processed"] = idx
                try:
                    data = self._ranxo_fetch_product_data(session, url, timeout)
                    if not data or not data.get("barcode"):
                        stats["no_sku"] += 1
                    else:
                        updated, created = self._merge_offline_entry(data["barcode"], data, "Ranxo")
                        if updated:
                            stats["success"] += 1
                        if created:
                            stats["new"] += 1
                except Exception:
                    stats["errors"] += 1

                if idx % 5 == 0 or idx == stats["total"]:
                    self._emit_prefill_progress(on_progress, stats)

                if delay:
                    time.sleep(delay)

            if stats["success"] > 0:
                self._save_offline_cache()

            self._emit_prefill_progress(on_progress, stats, "Prefill concluido.")
            return stats

        finally:
            self.max_offline_entries = original_max

    def prefill_bazara_cache(self, on_progress=None, delay: float = 0.2):
        """
        Prefill do cache offline usando sitemap do Bazara (requer permissao).
        Executa em modo sequencial e salva uma unica vez no final.
        """
        stats = {
            "total": 0,
            "processed": 0,
            "success": 0,
            "new": 0,
            "no_sku": 0,
            "errors": 0,
        }
        original_max = self.max_offline_entries
        session = requests.Session()
        session.headers.update(getattr(BazaraAPI, "HEADERS", {}))
        timeout = getattr(BazaraAPI, "REQUEST_TIMEOUT", 6)

        try:
            url_keys = self._bazara_get_url_keys(session, timeout)
            stats["total"] = len(url_keys)

            if stats["total"] > self.max_offline_entries:
                self.max_offline_entries = stats["total"]

            self._emit_prefill_progress(on_progress, stats, "Iniciando prefill Bazara...")

            for idx, url_key in enumerate(url_keys, 1):
                stats["processed"] = idx
                try:
                    data = self._bazara_fetch_product_by_url_key(session, url_key, timeout)
                    if not data or not data.get("barcode"):
                        stats["no_sku"] += 1
                    else:
                        updated, created = self._merge_offline_entry(data["barcode"], data, "Bazara")
                        if updated:
                            stats["success"] += 1
                        if created:
                            stats["new"] += 1
                except Exception:
                    stats["errors"] += 1

                if idx % 5 == 0 or idx == stats["total"]:
                    self._emit_prefill_progress(on_progress, stats)

                if delay:
                    time.sleep(delay)

            if stats["success"] > 0:
                self._save_offline_cache()

            self._emit_prefill_progress(on_progress, stats, "Prefill concluido.")
            return stats

        finally:
            self.max_offline_entries = original_max

    def prefill_bazara_offline_cache(self, on_progress=None, delay: float = 0.2, reset: bool = False):
        """
        Prefill do cache offline do Bazara via GraphQL.
        Salva no arquivo bazara_offline_cache.json (separado do cache principal).
        """
        try:
            from api.bazara_prefill import prefill_bazara_cache
        except Exception:
            stats = {
                "total": 0,
                "processed": 0,
                "success": 0,
                "new": 0,
                "updated": 0,
                "no_sku": 0,
                "errors": 1,
                "pages": 0,
            }
            self._emit_prefill_progress(on_progress, stats, "Erro ao iniciar prefill Bazara.")
            return stats

        return prefill_bazara_cache(delay=delay, reset=reset, on_progress=on_progress)

    def backfill_bazara_barcodes(self, on_progress=None, delay: float = 0.2, limit: int | None = None):
        """
        Preenche codigos de barras no cache offline do Bazara usando GraphQL e pagina do produto.
        """
        try:
            from api.bazara_backfill_barcodes import backfill_barcodes
        except Exception:
            stats = {
                "total": 0,
                "processed": 0,
                "updated": 0,
                "skipped": 0,
                "no_barcode": 0,
                "errors": 1,
                "moved": 0,
            }
            self._emit_prefill_progress(on_progress, stats, "Erro ao iniciar backfill Bazara.")
            return stats

        return backfill_barcodes(delay=delay, limit=limit, on_progress=on_progress)

    def _bazara_get_url_keys(self, session, timeout: int):
        sitemap_url = "https://bazara.co.mz/sitemap.xml"
        xml_text = self._fetch_text_with_retries(session, sitemap_url, timeout, attempts=2)
        if not xml_text:
            return []
        return self._bazara_extract_url_keys(xml_text)

    def _bazara_extract_url_keys(self, xml_text: str):
        try:
            root = ET.fromstring(xml_text)
        except Exception:
            return []
        ns = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        keys = []
        for loc in root.findall(".//ns:url/ns:loc", ns):
            value = (loc.text or "").strip()
            if not value:
                continue
            path = urlparse(value).path
            last = path.split("/")[-1]
            if not last.endswith(".html"):
                continue
            key = last[:-5].strip()
            if key:
                keys.append(key)
        seen = set()
        ordered = []
        for key in keys:
            if key not in seen:
                seen.add(key)
                ordered.append(key)
        return ordered

    def _bazara_fetch_product_by_url_key(self, session, url_key: str, timeout: int):
        if not url_key:
            return None
        url = "https://bazara.co.mz/graphql"
        query = (
            "query ($key: String!) { "
            "products(filter: { url_key: { eq: $key } }) { "
            "items { "
            "name sku url_key "
            "small_image { url } "
            "image { url } "
            "price_range { minimum_price { final_price { value currency } } } "
            "categories { name } "
            "} } }"
        )
        payload = {"query": query, "variables": {"key": url_key}}
        headers = {
            "User-Agent": getattr(BazaraAPI, "HEADERS", {}).get("User-Agent", "Mozilla/5.0"),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        response = self._post_json_with_retries(session, url, payload, headers, timeout, attempts=2)
        if not response:
            return None
        items = (((response.get("data") or {}).get("products") or {}).get("items")) or []
        if not items:
            return None
        item = items[0] or {}

        sku = (item.get("sku") or "").strip()
        if not self._bazara_valid_sku(sku):
            return {"barcode": None}

        name = item.get("name") or ""
        price = self._bazara_extract_graphql_price(item)
        image = self._bazara_extract_graphql_image(item)
        category = self._bazara_extract_graphql_category(item)

        return {
            "barcode": sku,
            "name": name,
            "price": price,
            "image": image,
            "category": category,
        }

    @staticmethod
    def _bazara_valid_sku(sku: str) -> bool:
        return bool(str(sku).strip())

    @staticmethod
    def _bazara_extract_graphql_price(item: dict) -> str:
        price_range = item.get("price_range") or {}
        minimum = price_range.get("minimum_price") or {}
        final_price = minimum.get("final_price") or {}
        value = final_price.get("value")
        if value is None:
            return ""
        try:
            return str(value)
        except Exception:
            return ""

    @staticmethod
    def _bazara_extract_graphql_image(item: dict) -> str:
        small = item.get("small_image") or {}
        image = item.get("image") or {}
        return small.get("url") or image.get("url") or ""

    def _bazara_extract_graphql_category(self, item: dict) -> str | None:
        categories = item.get("categories") or []
        preferred = None
        for cat in categories:
            name = (cat or {}).get("name")
            if not name:
                continue
            lowered = str(name).strip().lower()
            if lowered in {"todos produtos", "todos os produtos", "todos"}:
                continue
            preferred = name
            break
        if not preferred and categories:
            preferred = (categories[0] or {}).get("name")
        if not preferred:
            return None
        return BazaraAPI.CATEGORY_MAP.get(preferred, preferred)

    @staticmethod
    def _fetch_text_with_retries(session, url: str, timeout: int, attempts: int = 2):
        for _ in range(max(attempts, 1)):
            try:
                resp = session.get(url, timeout=timeout)
                if resp.status_code == 200:
                    return resp.text
            except Exception:
                continue
        return None

    @staticmethod
    def _post_json_with_retries(session, url: str, payload: dict, headers: dict, timeout: int, attempts: int = 2):
        for _ in range(max(attempts, 1)):
            try:
                resp = session.post(url, json=payload, headers=headers, timeout=timeout)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                if isinstance(data, dict) and not data.get("errors"):
                    return data
            except Exception:
                continue
        return None

    def refresh_offline_cache_from_apis(
        self,
        source_names=None,
        on_progress=None,
        delay: float = 0.2,
    ):
        """
        Atualiza o cache offline usando os barcodes existentes e APIs externas.
        Salva o arquivo uma unica vez no final.
        """
        stats = {
            "total": 0,
            "processed": 0,
            "found": 0,
            "updated": 0,
            "errors": 0,
        }
        barcodes = list(self.offline_cache.keys())
        stats["total"] = len(barcodes)

        if not barcodes:
            self._emit_prefill_progress(on_progress, stats, "Cache offline vazio.")
            return stats

        if source_names:
            wanted = {str(name).lower() for name in source_names}
            sources = [(n, api) for n, api in self.EXTERNAL_SOURCES if n.lower() in wanted]
        else:
            sources = list(self.EXTERNAL_SOURCES)

        if not sources:
            self._emit_prefill_progress(on_progress, stats, "Nenhuma API configurada.")
            return stats

        self._emit_prefill_progress(on_progress, stats, "Atualizando cache online...")
        openfoodfacts_updated = False

        for idx, barcode in enumerate(barcodes, 1):
            stats["processed"] = idx
            for source_name, api in sources:
                try:
                    self._emit_prefill_progress(
                        on_progress,
                        stats,
                        f"Buscando {barcode} em {source_name}...",
                    )
                    result = self._fetch_with_timeout(api, barcode, self.timeout_per_api)
                    if not result:
                        continue
                    stats["found"] += 1
                    if isinstance(result, dict) and not result.get("barcode"):
                        result = dict(result)
                        result["barcode"] = barcode
                    updated, _created = self._merge_offline_entry(barcode, result, source_name)
                    if updated:
                        stats["updated"] += 1
                    if self._is_openfoodfacts_source(source_name, result):
                        self._upsert_openfoodfacts_cache(barcode, result)
                        openfoodfacts_updated = True
                except Exception:
                    stats["errors"] += 1

            if idx % 5 == 0 or idx == stats["total"]:
                self._emit_prefill_progress(on_progress, stats)
            if delay:
                time.sleep(delay)

        self._save_offline_cache()
        if openfoodfacts_updated:
            self._save_openfoodfacts_cache()
        self._emit_prefill_progress(on_progress, stats, "Atualizacao concluida.")
        return stats

    def _emit_prefill_progress(self, on_progress, stats: dict, message: str | None = None):
        if not on_progress:
            return
        payload = dict(stats)
        if message:
            payload["message"] = message
        on_progress(payload)

    def _ranxo_get_sitemap_urls(self, session, timeout: int):
        index_url = "https://www.ranxo.co.mz/wp-sitemap.xml"
        response = session.get(index_url, timeout=timeout)
        if response.status_code != 200:
            return []
        return self._ranxo_extract_sitemap_urls(response.text)

    def _ranxo_extract_sitemap_urls(self, xml_text: str):
        try:
            root = ET.fromstring(xml_text)
        except Exception:
            return []
        ns = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls = []
        for loc in root.findall(".//ns:sitemap/ns:loc", ns):
            value = (loc.text or "").strip()
            if "wp-sitemap-posts-product" in value:
                urls.append(value)
        return urls

    def _ranxo_get_product_urls(self, session, sitemap_urls, timeout: int):
        product_urls = []
        for sitemap_url in sitemap_urls:
            try:
                response = session.get(sitemap_url, timeout=timeout)
                if response.status_code != 200:
                    continue
                product_urls.extend(self._ranxo_extract_product_urls(response.text))
            except Exception:
                continue
        # Deduplicar mantendo ordem
        seen = set()
        ordered = []
        for url in product_urls:
            if url not in seen:
                seen.add(url)
                ordered.append(url)
        return ordered

    def _ranxo_extract_product_urls(self, xml_text: str):
        try:
            root = ET.fromstring(xml_text)
        except Exception:
            return []
        ns = {"ns": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        urls = []
        for loc in root.findall(".//ns:url/ns:loc", ns):
            value = (loc.text or "").strip()
            if value:
                urls.append(value)
        return urls

    def _ranxo_fetch_product_data(self, session, product_url: str, timeout: int):
        response = session.get(product_url, timeout=timeout, allow_redirects=True)
        if response.status_code != 200:
            return None
        soup = BeautifulSoup(response.text, "html.parser")

        sku = self._ranxo_extract_sku(soup)
        if not self._ranxo_valid_sku(sku):
            return {"barcode": None}

        name = self._ranxo_extract_name(soup)
        price_text = self._ranxo_extract_price(soup)
        price = RanxoAPI.normalize_price(price_text)
        image = self._ranxo_extract_image(soup)
        category = self._ranxo_extract_category(soup)

        return {
            "barcode": sku,
            "name": name,
            "price": price,
            "image": image,
            "category": category,
        }

    @staticmethod
    def _ranxo_extract_sku(soup: BeautifulSoup) -> str:
        sku_tag = soup.select_one("span.sku")
        return sku_tag.get_text(strip=True) if sku_tag else ""

    @staticmethod
    def _ranxo_extract_name(soup: BeautifulSoup) -> str:
        name_tag = soup.select_one("h1.product_title")
        return name_tag.get_text(strip=True) if name_tag else ""

    @staticmethod
    def _ranxo_extract_price(soup: BeautifulSoup) -> str:
        price_tag = soup.select_one(".price")
        return price_tag.get_text(" ", strip=True) if price_tag else ""

    @staticmethod
    def _ranxo_extract_image(soup: BeautifulSoup) -> str:
        meta = soup.select_one('meta[property="og:image"]')
        if meta and meta.has_attr("content"):
            return meta["content"]
        img = soup.select_one("figure.woocommerce-product-gallery__wrapper img, .woocommerce-product-gallery__image img")
        if img and img.has_attr("src"):
            return img["src"]
        return ""

    @staticmethod
    def _ranxo_extract_category(soup: BeautifulSoup) -> str | None:
        crumbs = [a.get_text(strip=True) for a in soup.select("nav.woocommerce-breadcrumb a")]
        if crumbs:
            for name in reversed(crumbs):
                if name and name.lower() not in ("inicio", "início"):
                    return name
        posted = soup.select(".posted_in a")
        if posted:
            return posted[0].get_text(strip=True)
        return None

    @staticmethod
    def _ranxo_valid_sku(sku: str) -> bool:
        if not sku:
            return False
        cleaned = str(sku).strip()
        if len(cleaned) < 8:
            return False
        return cleaned.isalnum()

    def _merge_offline_entry(self, barcode: str, new_data: dict, source: str):
        created = False
        updated = False

        entry = self.offline_cache.get(barcode)
        if not entry:
            created = True
            entry = {
                "source": source,
                "data": {"barcode": barcode},
                "timestamp": datetime.now().isoformat(),
            }
            self.offline_cache[barcode] = entry

        data = entry.get("data") or {}
        if not data.get("barcode"):
            data["barcode"] = barcode
            updated = True

        for key, value in (new_data or {}).items():
            if not value:
                continue
            if not data.get(key):
                data[key] = value
                updated = True

        chain = data.get("source_chain")
        if isinstance(chain, list):
            if source not in chain:
                chain.append(source)
                data["source_chain"] = chain
                updated = True
        elif chain is None:
            data["source_chain"] = [source]
            updated = True

        entry["data"] = data
        if updated:
            if not entry.get("source"):
                entry["source"] = source
            entry["timestamp"] = datetime.now().isoformat()

        return updated, created
