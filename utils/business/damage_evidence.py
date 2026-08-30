"""Preparacao e armazenamento privado de fotos para perdas por dano."""

from __future__ import annotations

from io import BytesIO
import hashlib
import os
from pathlib import Path
from uuid import uuid4

from utils.config.paths import data_path, relativize_to_root, resolve_path


MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_FORMATS = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
    "WEBP": ("image/webp", ".webp"),
}


class DamageEvidenceError(ValueError):
    """Erro controlado que pode ser mostrado ao atendente."""


def _load_pillow():
    try:
        from PIL import Image, UnidentifiedImageError
        return Image, UnidentifiedImageError
    except Exception as exc:  # pragma: no cover - dependente da instalacao
        raise DamageEvidenceError(
            "Preparacao de imagem indisponivel: instale a dependencia Pillow."
        ) from exc


def prepare_damage_image(raw_bytes: bytes, filename: str = "evidencia") -> dict:
    """Valida a imagem e remove EXIF, devolvendo bytes seguros para guardar."""
    raw_bytes = bytes(raw_bytes or b"")
    if not raw_bytes:
        raise DamageEvidenceError("Selecione uma imagem para a evidencia.")
    if len(raw_bytes) > MAX_IMAGE_BYTES:
        raise DamageEvidenceError("A imagem deve ter no maximo 10 MB.")

    Image, UnidentifiedImageError = _load_pillow()
    try:
        with Image.open(BytesIO(raw_bytes)) as source:
            source.verify()
        with Image.open(BytesIO(raw_bytes)) as source:
            image_format = str(source.format or "").upper()
            if image_format not in ALLOWED_FORMATS:
                raise DamageEvidenceError("Use uma imagem JPEG, PNG ou WebP.")
            # A copia separa os pixels de EXIF e de outros metadados do ficheiro.
            image = source.copy()
    except DamageEvidenceError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise DamageEvidenceError("O ficheiro selecionado nao e uma imagem valida.") from exc

    if image.width < 80 or image.height < 80:
        raise DamageEvidenceError("A imagem e demasiado pequena para servir de evidencia.")

    mime_type, extension = ALLOWED_FORMATS[image_format]
    output = BytesIO()
    save_kwargs = {}
    if image_format == "JPEG":
        if image.mode not in {"RGB", "L"}:
            image = image.convert("RGB")
        save_kwargs.update(quality=90, optimize=True)
    elif image_format == "PNG" and image.mode not in {"RGB", "RGBA", "L", "LA"}:
        image = image.convert("RGBA")
    elif image_format == "WEBP":
        save_kwargs.update(quality=90, method=4)
    image.save(output, format=image_format, **save_kwargs)
    data = output.getvalue()
    if len(data) > MAX_IMAGE_BYTES:
        raise DamageEvidenceError("A imagem preparada ultrapassa o limite de 10 MB.")

    return {
        "data": data,
        "mime_type": mime_type,
        "extension": extension,
        "sha256": hashlib.sha256(data).hexdigest(),
        "file_size": len(data),
        "filename": Path(str(filename or "evidencia")).name,
    }


def prepare_damage_image_file(source_path: str | os.PathLike[str]) -> dict:
    path = Path(source_path)
    try:
        if not path.is_file():
            raise DamageEvidenceError("O ficheiro de evidencia nao foi encontrado.")
        if path.stat().st_size > MAX_IMAGE_BYTES:
            raise DamageEvidenceError("A imagem deve ter no maximo 10 MB.")
        return prepare_damage_image(path.read_bytes(), path.name)
    except DamageEvidenceError:
        raise
    except OSError as exc:
        raise DamageEvidenceError("Nao foi possivel ler a imagem selecionada.") from exc


def store_prepared_evidence(prepared: dict, evidence_id: str | None = None) -> tuple[str, str]:
    """Guarda uma imagem validada numa area privada e devolve ID e caminho relativo."""
    evidence_id = str(evidence_id or uuid4())
    relative = Path("data") / "evidence" / "losses" / evidence_id[:2] / f"{evidence_id}{prepared['extension']}"
    absolute = resolve_path(relative)
    absolute.parent.mkdir(parents=True, exist_ok=True)
    temp = absolute.with_suffix(absolute.suffix + ".tmp")
    try:
        temp.write_bytes(prepared["data"])
        os.replace(temp, absolute)
    except OSError as exc:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise DamageEvidenceError("Nao foi possivel guardar a foto do dano.") from exc
    return evidence_id, relativize_to_root(absolute)


def remove_stored_evidence(relative_path: str | None) -> None:
    """Remove apenas ficheiros dentro da pasta privada de evidencias."""
    if not relative_path:
        return
    base = data_path("evidence", "losses").resolve()
    try:
        target = resolve_path(relative_path).resolve()
        target.relative_to(base)
        target.unlink(missing_ok=True)
    except (OSError, ValueError):
        return


def create_damage_evidence_from_image(database, prepared: dict, created_by=None) -> dict:
    """Guarda uma foto obrigatoria sem enviar a imagem para servicos externos."""
    for stale_path in database.cleanup_unbound_damage_evidence(hours=24) or []:
        remove_stored_evidence(stale_path)

    evidence_id, storage_path = store_prepared_evidence(prepared)
    attachment = {
        "attached": True,
        "source": "OPERATOR",
        "summary": "Foto anexada pelo atendente.",
    }
    try:
        created = database.create_damage_evidence(
            evidence_id=evidence_id,
            storage_path=storage_path,
            sha256=prepared["sha256"],
            mime_type=prepared["mime_type"],
            file_size=prepared["file_size"],
            analysis=attachment,
            created_by=created_by,
        )
    except Exception:
        remove_stored_evidence(storage_path)
        raise
    if not created:
        remove_stored_evidence(storage_path)
        raise DamageEvidenceError("Nao foi possivel guardar a foto do dano.")
    return {
        "ok": True,
        "attached": True,
        "evidence_id": evidence_id,
        "storage_path": storage_path,
        "message": "Foto anexada. Pode registar a perda.",
    }


def create_local_damage_evidence(database, source_path, created_by=None) -> dict:
    """Fluxo SQLite: preparar e guardar a foto obrigatoria."""
    prepared = prepare_damage_image_file(source_path)
    return create_damage_evidence_from_image(database, prepared, created_by=created_by)
