from __future__ import annotations

import os
import platform
import subprocess
import time
import unicodedata
from typing import Any


def _import_win32print():
    try:
        import win32print  # type: ignore

        return win32print
    except Exception:
        return None


def list_system_printers() -> list[str]:
    win32print = _import_win32print()
    if win32print is None:
        return []
    try:
        flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
        return sorted(
            {
                str(item[2]).strip()
                for item in win32print.EnumPrinters(flags)
                if len(item) > 2 and str(item[2] or "").strip()
            }
        )
    except Exception:
        return []


def get_default_printer_name() -> str:
    win32print = _import_win32print()
    if win32print is None:
        return ""
    try:
        return str(win32print.GetDefaultPrinter() or "").strip()
    except Exception:
        return ""


def _plain_text(value: Any) -> str:
    text = str(value or "").strip()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return "".join(char if char.isprintable() else " " for char in text)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _money(value: Any) -> str:
    return f"{_safe_float(value):,.2f} MZN".replace(",", " ")


def _line(width: int, char: str = "-") -> str:
    return char * max(1, width)


def _center(text: str, width: int) -> str:
    return _plain_text(text)[:width].center(width)


def _left_right(left: str, right: str, width: int) -> str:
    left = _plain_text(left)
    right = _plain_text(right)
    gap = width - len(left) - len(right)
    if gap < 1:
        left = left[: max(0, width - len(right) - 1)]
        gap = width - len(left) - len(right)
    return f"{left}{' ' * max(1, gap)}{right}"


def _wrap_text(text: str, width: int) -> list[str]:
    text = _plain_text(text)
    if len(text) <= width:
        return [text]
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word[:width]
    if current:
        lines.append(current)
    return lines or [text[:width]]


def format_receipt_text(receipt_data: dict[str, Any], paper_width_mm: int = 80) -> str:
    width = 32 if int(paper_width_mm or 80) <= 58 else 42
    lines: list[str] = []

    lines.append(_center(receipt_data.get("store_name") or "MERCEARIA", width))
    lines.append(_center("RECIBO DE VENDA", width))
    receipt_code = _plain_text(receipt_data.get("receipt_code") or "")
    if receipt_code:
        lines.append(_center(f"Ref. {receipt_code}", width))
    lines.append(_line(width))
    lines.append(_left_right("Data", receipt_data.get("issued_at") or "", width))
    lines.append(_left_right("Operador", receipt_data.get("operator") or "Sistema", width))
    lines.append(_line(width))

    for item in receipt_data.get("items") or []:
        name_lines = _wrap_text(item.get("name") or "Produto", width)
        lines.extend(name_lines[:2])
        qty_text = _plain_text(item.get("qty_text") or "-")
        unit_price = _money(item.get("unit_price"))
        line_total = _money(item.get("line_total"))
        lines.append(_left_right(f"{qty_text} x {unit_price}", line_total, width))
        detail_parts = [
            _plain_text(item.get("sale_mode_label") or ""),
            _plain_text(item.get("vat_tag") or ""),
        ]
        detail = " | ".join(part for part in detail_parts if part)
        if detail:
            lines.append(detail[:width])

    lines.append(_line(width))
    lines.append(_left_right("Subtotal", _money(receipt_data.get("subtotal")), width))
    lines.append(_left_right("IVA", _money(receipt_data.get("vat_total")), width))
    if receipt_data.get("paid_amount") is not None:
        lines.append(_left_right("Pago", _money(receipt_data.get("paid_amount")), width))
    if receipt_data.get("change_amount") is not None:
        lines.append(_left_right("Troco", _money(receipt_data.get("change_amount")), width))
    lines.append(_line(width, "="))
    lines.append(_left_right("TOTAL", _money(receipt_data.get("total")), width))
    lines.append(_line(width, "="))

    vat_note = _plain_text(receipt_data.get("vat_note") or "")
    if vat_note:
        lines.extend(_wrap_text(vat_note, width)[:4])
        lines.append("")

    lines.append(_center("Obrigado pela preferencia.", width))
    return "\n".join(lines).rstrip() + "\n\n\n"


def print_thermal_receipt(
    receipt_data: dict[str, Any],
    printer_name: str = "",
    paper_width_mm: int = 80,
) -> tuple[bool, str]:
    win32print = _import_win32print()
    if win32print is None:
        return False, "Modulo pywin32 nao esta instalado para impressao direta."

    selected_printer = str(printer_name or "").strip() or get_default_printer_name()
    if not selected_printer:
        return False, "Nenhuma impressora configurada no Windows."

    text = format_receipt_text(receipt_data, paper_width_mm=paper_width_mm)
    payload = b"\x1b@" + text.encode("cp850", errors="replace") + b"\x1dV\x00"

    printer_handle = None
    try:
        printer_handle = win32print.OpenPrinter(selected_printer)
        job_name = f"Recibo venda {int(time.time())}"
        win32print.StartDocPrinter(printer_handle, 1, (job_name, None, "RAW"))
        try:
            win32print.StartPagePrinter(printer_handle)
            win32print.WritePrinter(printer_handle, payload)
            win32print.EndPagePrinter(printer_handle)
        finally:
            win32print.EndDocPrinter(printer_handle)
        return True, f"Recibo enviado para {selected_printer}."
    except Exception as exc:
        return False, f"Falha ao imprimir na termica: {exc}"
    finally:
        if printer_handle is not None:
            try:
                win32print.ClosePrinter(printer_handle)
            except Exception:
                pass


def print_pdf_with_system(pdf_path: str, printer_name: str = "") -> tuple[bool, str]:
    if not os.path.exists(pdf_path):
        return False, f"Arquivo nao encontrado: {pdf_path}"

    absolute_path = os.path.abspath(pdf_path)
    system = platform.system()
    try:
        if system == "Windows":
            if printer_name:
                try:
                    import win32api  # type: ignore

                    win32api.ShellExecute(
                        0,
                        "printto",
                        absolute_path,
                        f'"{printer_name}"',
                        ".",
                        0,
                    )
                    return True, f"PDF enviado para {printer_name}."
                except Exception:
                    pass
            os.startfile(absolute_path, "print")  # type: ignore[attr-defined]
            return True, "PDF enviado para a impressora padrao."
        if system == "Darwin":
            subprocess.Popen(["lp", absolute_path])
            return True, "PDF enviado para a fila de impressao."
        subprocess.Popen(["lp", absolute_path])
        return True, "PDF enviado para a fila de impressao."
    except Exception as exc:
        return False, f"Erro ao imprimir PDF: {exc}"
