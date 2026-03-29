"""
Gerador de PIX QR Code — Padrão EMV BRCode.
Gera payload e imagem QR para pagamentos estáticos.
"""

import io
import base64
from binascii import crc_hqx


def _tlv(tag: str, value: str) -> str:
    """Monta um campo TLV (Tag-Length-Value) do EMV."""
    length = f"{len(value):02d}"
    return f"{tag}{length}{value}"


def generate_pix_payload(
    pix_key: str,
    merchant_name: str,
    merchant_city: str,
    amount: float | None = None,
    txid: str = "***",
    description: str = "",
) -> str:
    """
    Gera o payload PIX (BRCode) no padrão EMV.
    - pix_key: chave PIX (email, CPF, telefone, aleatória)
    - merchant_name: nome do recebedor (max 25 chars)
    - merchant_city: cidade (max 15 chars)
    - amount: valor em reais (None = valor livre)
    - txid: identificador da transação
    """
    # ID 00 - Payload Format Indicator
    payload = _tlv("00", "01")

    # ID 26 - Merchant Account Information (PIX)
    gui = _tlv("00", "br.gov.bcb.pix")
    key = _tlv("01", pix_key)
    if description:
        desc = _tlv("02", description[:25])
        merchant_info = gui + key + desc
    else:
        merchant_info = gui + key
    payload += _tlv("26", merchant_info)

    # ID 52 - Merchant Category Code
    payload += _tlv("52", "0000")

    # ID 53 - Transaction Currency (986 = BRL)
    payload += _tlv("53", "986")

    # ID 54 - Transaction Amount (opcional)
    if amount is not None and amount > 0:
        amount_str = f"{amount:.2f}"
        payload += _tlv("54", amount_str)

    # ID 58 - Country Code
    payload += _tlv("58", "BR")

    # ID 59 - Merchant Name (max 25)
    payload += _tlv("59", merchant_name[:25])

    # ID 60 - Merchant City (max 15)
    payload += _tlv("60", merchant_city[:15])

    # ID 62 - Additional Data Field
    txid_field = _tlv("05", txid[:25])
    payload += _tlv("62", txid_field)

    # ID 63 - CRC16 (placeholder + cálculo)
    payload += "6304"
    crc = crc_hqx(payload.encode("utf-8"), 0xFFFF)
    crc_hex = f"{crc:04X}"
    payload += crc_hex

    return payload


def generate_pix_qrcode_base64(
    pix_key: str,
    merchant_name: str,
    merchant_city: str,
    amount: float | None = None,
    txid: str = "***",
    description: str = "",
) -> str:
    """
    Gera o QR Code PIX como string base64 (para exibir em <img src="data:image/png;base64,...">).
    """
    import qrcode

    payload = generate_pix_payload(
        pix_key=pix_key,
        merchant_name=merchant_name,
        merchant_city=merchant_city,
        amount=amount,
        txid=txid,
        description=description,
    )

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(payload)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)

    b64 = base64.b64encode(buffer.read()).decode("utf-8")
    return b64


def generate_pix_qrcode_bytes(
    pix_key: str,
    merchant_name: str,
    merchant_city: str,
    amount: float | None = None,
    txid: str = "***",
    description: str = "",
) -> bytes:
    """Gera o QR Code PIX como bytes PNG."""
    import qrcode

    payload = generate_pix_payload(
        pix_key=pix_key,
        merchant_name=merchant_name,
        merchant_city=merchant_city,
        amount=amount,
        txid=txid,
        description=description,
    )

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=3,
    )
    qr.add_data(payload)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer.read()
