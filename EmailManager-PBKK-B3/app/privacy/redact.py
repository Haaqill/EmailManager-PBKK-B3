"""Redaksi PII dengan placeholder yang bisa dipulihkan (Fase 1.2).

Prinsip (sesuai roadmap):
- Nilai sensitif diganti placeholder yang KONSISTEN per sesi:
  `<PERSON_1>`, `<EMAIL_1@domain>`, `<PHONE_1>`, `<ACCOUNT_1>`.
  Nilai yang sama selalu mendapat placeholder yang sama.
- Tabel pemetaan hanya ada di memori objek `PIIRedactor` (tidak ditulis ke disk,
  tidak tampil di repr). Panggil `clear()` saat sesi selesai.
- Domain email tetap terlihat (mis. `<EMAIL_2@univ.ac.id>`) karena penting
  untuk klasifikasi.
- Rahasia dihapus permanen dengan `[SECRET]` dan tidak bisa dipulihkan:
  API key, token, password/OTP/PIN, nomor kartu yang lolos uji Luhn, NIK.
- HTML diubah menjadi teks polos; script/style, gambar (termasuk tracking pixel),
  data base64, dan karakter zero-width dibuang.
- Nomor telepon format Indonesia (+62 / 62 / 08xx, serta telepon rumah dengan
  kode area) dikenali; tanggal, NIM, nomor surat, dan nominal tidak ikut terhapus.

- Teks masuk yang sudah berbentuk placeholder ("<PHONE_1>" yang ditulis pengirim)
  dinetralkan menjadi "‹PHONE_1>" agar tidak bisa dipulihkan menjadi data orang lain.
  Akibatnya: redaksi hanya untuk teks MENTAH; jangan meredaksi teks yang sudah diredaksi.

Keterbatasan yang disengaja: nama orang di isi email hanya dikenali jika muncul di
header (From/To/Cc), di baris kutipan "Nama <alamat>", didaftarkan lewat
`register_person`/`extra_names`, atau didahului sapaan/gelar (Bapak, Ibu, Sdr., a.n.,
Dear, Halo, ...). Tidak ada NER.
"""
from __future__ import annotations

import html
import re
import unicodedata
from email.header import decode_header, make_header
from email.utils import getaddresses
from html.parser import HTMLParser
from typing import Any, Callable, Iterable
from urllib.parse import unquote, urlparse
from app.contracts import PiiMap as PiiMapProtocol

SECRET = "[SECRET]"

# --------------------------------------------------------------------------- #
# Placeholder
# --------------------------------------------------------------------------- #
PLACEHOLDER_RE = re.compile(
    r"<(?P<kind>PERSON|EMAIL|PHONE|ACCOUNT)_(?P<num>\d+)(?:@(?P<dom>[A-Za-z0-9.-]+))?>|\[SECRET\]"
)
# Teks email masuk yang sudah berbentuk placeholder (mis. "<PHONE_1>" yang ditulis
# penyerang) dinetralkan agar tidak bisa dipulihkan menjadi data asli orang lain.
_INJECTED_PLACEHOLDER_RE = re.compile(r"<(?=\s*(?:PERSON|EMAIL|PHONE|ACCOUNT)_\d)", re.IGNORECASE)
NEUTRALISED_BRACKET = "\u2039"   # ‹

# --------------------------------------------------------------------------- #
# Rahasia (dihapus permanen)
# --------------------------------------------------------------------------- #
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
    re.compile(r"\beyJ[\w-]{5,}\.[\w-]{5,}\.[\w-]{5,}"),            # JWT
    re.compile(r"\bsk-(?:proj-|ant-)?[A-Za-z0-9_-]{16,}"),          # OpenAI/Anthropic-style
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),                        # Google API key
    re.compile(r"\bya29\.[0-9A-Za-z_-]{20,}"),                      # Google access token
    re.compile(r"(?<![\w/])1//[0-9A-Za-z_-]{20,}"),                 # Google refresh token
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),                    # GitHub token
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),                  # Slack token
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                            # AWS access key id
]
_BEARER_RE = re.compile(r"(?i)\b(bearer)(\s+)[A-Za-z0-9._~+/=-]{12,}")

# Dua keluarga label rahasia dengan aturan nilai yang berbeda:
#  - kode sekali pakai (OTP/PIN/kode verifikasi): nilainya HARUS berbentuk kode angka 4–8 digit;
#  - kata sandi / token / key: wajib ada pemisah (":", "=", "is", "adalah"), kecuali kata sandi
#    yang langsung diikuti token campuran huruf+angka ("password budi2026").
_OTP_LABELS = (
    r"otp|pin|kode\s+otp|kode\s+verifikasi|kode\s+keamanan|kode\s+akses|kode\s+login|"
    r"kode\s+(?:anda|kamu)|your\s+code|gunakan\s+kode|masukkan\s+kode|use\s+code|enter\s+code|"
    r"(?:verification|security|login|confirmation)\s+code|one[- ]time\s+(?:password|code)"
)
# Kata yang menandakan kalimat biasa, bukan "label → kode": "OTP dikirim ke ...", "berlaku 300 detik"
_GAP_STOP = (
    r"(?:is|adalah|ialah|ke|to|via|on|pada|dalam|selama|for|at|in|di|berlaku|dikirim|sent|"
    r"expired|expires|expire|valid|kedaluwarsa|hingga|until|sampai|tidak|not|jangan|never|bukan)"
)
_OTP_VALUE = (
    r"(?<![\w/.-])(?:[A-Za-z]-)?(?:\d{4,8}|\d{1,4}(?:[ -]\d{1,4}){1,3})"
    r"(?![\w/%]|[.,]\d|[ \t]*(?:detik|menit|jam|hari|seconds?|minutes?|hours?|days?|halaman|pages?|%))"
)
_OTP_SECRET_RE = re.compile(
    rf"(?i)(?<!\[)\b({_OTP_LABELS})\b"
    rf"((?:[ \t]+(?!{_GAP_STOP}\b)[^\s\d:=<>\[\]]+){{0,4}}?"
    r"[ \t]*(?:[:=]|\bis\b|\badalah\b|\bialah\b|\bmenjadi\b|\bbecomes?\b)?[ \t]*(?:\n[ \t]*){0,3})"
    rf"({_OTP_VALUE})"
)
# "Kode: 482913" (label "kode" tepat sebelum titik dua, tanpa kata lain seperti "Kode pos:")
_BARE_KODE_RE = re.compile(r"(?i)(?<!\[)\b(kode|code)([ \t]*:[ \t]*)" + "(" + _OTP_VALUE + ")")
# "482913 adalah kode OTP Anda", "G-482913 is your Google verification code"
_REVERSE_OTP_RE = re.compile(
    r"(?i)(?<![\w-])(?:[a-z]-)?\d{4,8}(?![\w])"
    r"(?=[ \t]+(?:adalah|is|merupakan)[ \t]+"
    r"(?:kode[ \t]+(?:otp|verifikasi|keamanan|login)|otp|"
    r"your[ \t]+(?:[\w-]+[ \t]+){0,2}?(?:verification[ \t]+|security[ \t]+|login[ \t]+|confirmation[ \t]+)?code)\b)"
)
_PASSWORD_LABELS = r"password|passwd|pwd|passcode|kata\s*sandi|sandi|(?<![A-Za-z][ \t])pass"
_PASSWORD_GAP = r"(?:[ \t]+(?:akun|anda|kamu|baru|sementara|lama|wifi|email|your|new|temporary|default|awal)){0,3}"
_SEP_STRONG = r"[ \t]*(?:[:=]|\bis\b[ \t]*:?|\badalah\b[ \t]*:?|\bialah\b)[ \t]*(?:\n[ \t]*){0,2}"
_PASSWORD_SECRET_RE = re.compile(
    rf"(?i)(?<!\[)\b({_PASSWORD_LABELS})\b({_PASSWORD_GAP}{_SEP_STRONG})"
    r"(?!https?://)(?!\[SECRET\])([^\s<>@]+)(?![^\s<>]*@)"
)
# "password budi2026": langsung diikuti token campuran huruf+angka (bukan tanggal)
_PASSWORD_INLINE_RE = re.compile(
    rf"(?i)(?<!\[)\b({_PASSWORD_LABELS})\b([ \t]+)"
    r"(?=[^\s<>]*[A-Za-z])(?=[^\s<>]*\d)(?![\d-]+\b)([^\s<>@]{6,})"
)
_TOKEN_LABELS = (
    r"api[\s_-]?key|secret[\s_-]?key|client[\s_-]?secret|secret|token|access[\s_-]?token|"
    r"refresh[\s_-]?token|auth[\s_-]?token"
)
_TOKEN_SECRET_RE = re.compile(
    rf"(?i)(?<!\[)\b({_TOKEN_LABELS})\b([ \t]*[:=][ \t]*)"
    r"(?!https?://)(?![^\s<>]*\[SECRET\])"
    r"(?=[^\s<>]*[A-Za-z])(?=[^\s<>]*\d)(?!\d{4}-\d{2}-\d{2}\b)([^\s<>@]{8,})"
)
# Label identitas non-pribadi yang TEPAT berada di depan angka. Kata kontak (HP/WA/telp/kartu)
# di sekitarnya membatalkan pengecualian, agar nomor HP/kartu asli tidak lolos.
_PHONE_ID_LABEL_RE = re.compile(
    r"(?i)\b(?:nim|npm|nrp|nis|nisn|nip|isbn|awb|resi(?:[ \t]+[A-Z]{2,8})?|nomor[ \t]+surat|no\.?[ \t]*surat|"
    r"surat|kode[ \t]+bayar|virtual[ \t]+account|va|no\.?[ \t]*pendaftaran|registrasi|invoice|inv)"
    r"[ \t]*(?:no\.?|nomor|#)?[ \t]*[:#]?[ \t]*$"
)
_CARD_ID_LABEL_RE = re.compile(
    r"(?i)\b(?:order(?:[ \t]+id)?|pesanan|ref(?:erensi)?|id|invoice|inv|transaksi|booking|tracking|"
    r"resi|awb|tiket|no\.?[ \t]*pendaftaran|registrasi|isbn|kode[ \t]+bayar|virtual[ \t]+account|va)"
    r"[ \t]*(?:no\.?|nomor|#)?[ \t]*[:#]?[ \t]*$"
)
_CONTACT_WORD_RE = re.compile(
    r"(?i)\b(?:hp|wa|whatsapp|telp|telepon|tel|phone|ponsel|handphone|hubungi|kontak|contact|call|"
    r"sms|line|kartu|card|cc|kredit|credit|debit|visa|mastercard)\b"
)


def _id_context(segment: str, pos: int, kind: str = "phone") -> bool:
    """True jika angka di `pos` jelas nomor identitas non-pribadi (NIM, resi, surat, order ID)."""
    window = segment[max(0, pos - 40):pos]
    if _CONTACT_WORD_RE.search(window):
        return False
    label_re = _PHONE_ID_LABEL_RE if kind == "phone" else _CARD_ID_LABEL_RE
    return bool(label_re.search(window))


_CARD_RE = re.compile(
    r"(?<![\w+])(?:\d{13,19}|\d{4}([ .-])\d{4}\1\d{4}\1\d{1,7}|\d{4}([ .-])\d{6}\2\d{4,5})(?![\w])"
)
_NIK_LABELED_RE = re.compile(
    r"(?i)\b(nik|ktp|no\.?\s*ktp|nomor\s+ktp|nomor\s+induk\s+kependudukan)(?:\b|(?=\d))"
    r"([^\n\d]{0,10})(\d[\d .-]{14,22}\d)"
)
_SIXTEEN_DIGITS_RE = re.compile(r"(?<![\w+])\d{16}(?![\w])")
_NIK_PROVINCES = {
    11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 31, 32, 33, 34, 35, 36,
    51, 52, 53, 61, 62, 63, 64, 65, 71, 72, 73, 74, 75, 76, 81, 82,
    91, 92, 93, 94, 95, 96,
}

# --------------------------------------------------------------------------- #
# PII yang bisa dipulihkan
# --------------------------------------------------------------------------- #
_EMAIL_RE = re.compile(r"(?<![\w.%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
# "Budi Santoso <budi@x.ac.id>" di baris kutipan balasan ("... menulis:" / "... wrote:")
_NAME_BEFORE_ADDR_RE = re.compile(
    r"(?<![^\W_])((?:[A-Z][a-z][\w'-]*)(?:[ \t]+[A-Z][a-z][\w'-]*){0,3})[ \t]*<[ \t]*"
    r"([A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})[ \t]*>"
)
_BRACKETED_EMAIL_RE = re.compile(
    r"<[ \t]*([A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})[ \t]*>"
)
_EMAIL_URLENC_RE = re.compile(r"(?<![\w.%+-])[A-Za-z0-9._+-]+%40[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")

_NOT_AFTER_NUM = r"(?<![\w+/])(?<!\d[.,-])"
_NOT_BEFORE_NUM = r"(?![\w/])(?![.,-]\d)"
_PHONE_SEP = r"(?:[ \t]?[.-][ \t]?|[ \t]|-?\n)?"
_MOBILE_RE = re.compile(
    _NOT_AFTER_NUM
    + r"(?:\(\+62\)|\+62|62|0)[ .-]?\(?8\d{1,3}\)?(?:" + _PHONE_SEP + r"\d{2,5}){1,3}"
    + _NOT_BEFORE_NUM
)
_LANDLINE_RE = re.compile(
    _NOT_AFTER_NUM
    + r"(?:\(0\d{1,3}\)[ ]?|0\d{1,3}[ -]|\(?\+62\)?[ .-]?\(?[1-79]\d{0,2}\)?[ .-])\d{3,4}"
    + _PHONE_SEP + r"\d{3,4}"
    + _NOT_BEFORE_NUM
)
_WHATSAPP_RE = re.compile(r"(?i)(wa\.me/|whatsapp\.com/send/?\?phone=)(\+?\d{9,15})")
_TRAILING_GROUP_RE = re.compile(_PHONE_SEP + r"\d+\)?$")
_ACCOUNT_RE = re.compile(
    r"(?i)\b(no(?:mor|\.)?\s*rek(?:ening)?\.?|rekening|account\s+(?:number|no\.?))"
    r"([^\n\d]{0,25}?)(\d[\d .-]{6,22}\d)(?!\d)"
)

_HONORIFIC = (
    r"(?:Bapak|Bpk\.?|Pak|Ibu|Bu|Sdr\.?|Sdri\.?|Saudara|Saudari|Mas|Mbak|Kak|Dik|a\.n\.?|atas nama|"
    r"Mr\.?|Mrs\.?|Ms\.?|Dr\.?|Prof\.?|Ir\.?|Drs\.?|Hj\.?|H\.|Dear|Halo|Hai|Hi|Hello|Yth\.?|Kepada)"
)
_NAME_TOKEN = r"[A-Z][a-z]{1,20}(?:[-'][A-Za-z][a-z]{0,20})?"
_HONORIFIC_NAME_RE = re.compile(
    r"(?:(?<=\s)|(?<=^)|(?<=[(\"',]))"
    + _HONORIFIC + r"(?:[ \t]+" + _HONORIFIC + r")*"
    r"[ \t]+"
    r"(" + _NAME_TOKEN + r"(?:[ \t]+" + _NAME_TOKEN + r"){0,3})",
    re.MULTILINE,
)
_NAME_STOPWORDS = {
    # peran/sapaan umum, bukan nama
    "dosen", "mahasiswa", "semua", "team", "tim", "customer", "pelanggan", "sir", "madam",
    "all", "admin", "kepala", "ketua", "dekan", "rektor", "panitia", "peserta", "bapak",
    "ibu", "kakak", "teman", "member", "friend", "friends", "students", "student", "user",
    "pengguna", "valued", "there", "everyone", "pembimbing", "wali", "koordinator",
    "kak", "mas", "mbak", "pak", "bu", "dik", "adik", "bro", "sis", "gan",
    "kota", "prodi", "program", "studi", "bagian", "fakultas", "universitas",
    # kata yang sering muncul setelah "Halo"/"Hai"
    "selamat", "pagi", "siang", "sore", "malam", "terima", "kasih", "mohon", "dengan",
    "untuk", "kami", "anda", "saya", "apa", "kabar", "good", "morning", "afternoon",
    "evening", "thanks", "thank", "please", "this", "the", "and", "dan", "yang",
    "hormat", "salam", "regards", "best", "kind", "sincerely",
    # sapaan/peran umum lain (temuan uji adversarial)
    "hiring", "manager", "manajer", "world", "kamu", "kalian", "guys", "gaes", "kawin",
    "presiden", "sayang", "bos", "boss", "rekan", "sobat", "adek", "warga", "tuan", "nyonya",
    "direktur", "staf", "staff", "hrd", "recruiter", "recruitment", "folks", "yth", "kepada",
    "editor", "reviewer", "penguji", "pengurus", "orang", "tua", "wali", "pembeli", "penjual",
}
_TITLE_TOKENS = {
    "dr", "prof", "ir", "drs", "dra", "hj", "h", "mr", "mrs", "ms", "bapak", "ibu", "pak",
    "bu", "sdr", "sdri", "bpk", "yth",
}
_ORG_HINTS = re.compile(
    r"(?i)\b(bagian|fakultas|universitas|univ|prodi|program studi|jurusan|tim|team|admin|info|"
    r"support|noreply|no-reply|official|store|shop|bank|layanan|customer|service|newsletter|"
    r"akademik|perpustakaan|biro|panitia|himpunan|bem|kampus|notification|notifikasi|"
    r"marketing|promo|sales|redaksi|helpdesk|it|direktorat|lembaga|koordinator|sekretariat|"
    r"dekanat|kaprodi|sistem|system|account|billing|notifikasi|pengumuman|beasiswa|keuangan|"
    r"asisten|aslab|lab|laboratorium|unit|ukm|organisasi|komunitas|klub|club|company|inc|pt|cv)\b"
)
_GENERIC_LOCALPARTS = re.compile(
    r"(?i)^(no-?reply|do-?not-?reply|info|admin|newsletter|news|promo|marketing|cs|support|"
    r"help|hello|halo|notifications?|notifikasi|mailer|team|sales|billing|akademik|humas)"
    r"([._+-].*)?$"
)

_ZERO_WIDTH_RE = re.compile(r"[\xad​-‏⁠-⁤﻿]")
_DATA_URI_RE = re.compile(r"data:[\w.+/-]+;base64,[A-Za-z0-9+/=\s]+")
_LONG_BASE64_RE = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{200,}={0,2}")

RISKY_EXTENSIONS = {
    ".exe", ".zip", ".rar", ".7z", ".js", ".vbs", ".bat", ".cmd", ".scr", ".msi", ".jar",
    ".iso", ".apk", ".ps1", ".lnk", ".hta", ".docm", ".xlsm", ".pptm", ".html", ".htm",
}


# --------------------------------------------------------------------------- #
# Validator
# --------------------------------------------------------------------------- #
def luhn_valid(digits: str) -> bool:
    if not digits.isdigit() or not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def looks_like_card(digits: str) -> bool:
    """Nomor kartu pembayaran: 13-19 digit, awalan jaringan kartu, lolos Luhn."""
    if digits[0] not in "23456":
        return False
    if digits.startswith("628"):  # lebih mungkin nomor HP +62 8xx
        return False
    return luhn_valid(digits)


def nik_valid(digits: str) -> bool:
    """Struktur NIK: provinsi(2) kab(2) kec(2) DDMMYY(6) urut(4)."""
    if len(digits) != 16 or not digits.isdigit():
        return False
    prov, kab, kec = int(digits[0:2]), int(digits[2:4]), int(digits[4:6])
    day, month = int(digits[6:8]), int(digits[8:10])
    serial = int(digits[12:16])
    if prov not in _NIK_PROVINCES or kab == 0 or kec == 0 or serial == 0:
        return False
    if not (1 <= day <= 31 or 41 <= day <= 71):
        return False
    return 1 <= month <= 12


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _phone_key(raw: str) -> str | None:
    """Normalisasi ke bentuk nasional tanpa awalan; None jika bukan nomor telepon."""
    d = _digits(raw)
    if raw.lstrip("( ").startswith("+62") or (d.startswith("62") and not raw.startswith("0")):
        national = d[2:]
    elif d.startswith("0"):
        national = d[1:]
    else:
        return None
    if national.startswith("8"):
        return national if 9 <= len(national) <= 12 else None
    return national if 8 <= len(national) <= 11 else None


# --------------------------------------------------------------------------- #
# HTML → teks
# --------------------------------------------------------------------------- #
class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "head", "title", "noscript", "template", "svg"}
    _BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table",
              "ul", "ol", "blockquote", "hr", "section", "article", "footer", "header"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0
        self._link_stack: list[tuple[str | None, int]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1
            return
        if tag in self._BLOCK:
            self.parts.append("\n")
        if tag == "a":
            href = dict(attrs).get("href") or ""
            host = urlparse(href).hostname if href.lower().startswith(("http://", "https://")) else None
            self._link_stack.append((host, len(self.parts)))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._BLOCK:
            self.parts.append("\n")
        # <img> (termasuk tracking pixel) sengaja dibuang

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "a" and self._link_stack:
            host, start = self._link_stack.pop()
            link_text = "".join(self.parts[start:])
            if host and host.lower() not in link_text.lower():
                self.parts.append(f" [link: {host}]")
        if tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)


def html_to_text(raw_html: str) -> str:
    parser = _TextExtractor()
    parser.feed(_DATA_URI_RE.sub("", raw_html))
    parser.close()
    return normalize_text("".join(parser.parts))


def normalize_text(text: str) -> str:
    text = html.unescape(text) if "&" in text and ";" in text else text
    # NFKC: huruf/angka lebar penuh ("＜PHONE_1＞", "０８１２") menjadi ASCII biasa
    text = unicodedata.normalize("NFKC", text)
    text = _ZERO_WIDTH_RE.sub("", text)
    text = _DATA_URI_RE.sub("", text)
    text = _LONG_BASE64_RE.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# --------------------------------------------------------------------------- #
# Redactor
# --------------------------------------------------------------------------- #
def _sub_outside_placeholders(text: str, pattern: re.Pattern[str],
                              repl: Callable[[re.Match[str]], str]) -> str:
    """Terapkan substitusi hanya pada bagian teks di luar placeholder yang sudah ada."""
    out: list[str] = []
    last = 0
    for ph in PLACEHOLDER_RE.finditer(text):
        out.append(pattern.sub(repl, text[last:ph.start()]))
        out.append(ph.group(0))
        last = ph.end()
    out.append(pattern.sub(repl, text[last:]))
    return "".join(out)


_DEGREE_TOKEN_RE = re.compile(r"^(?:[A-Z][A-Za-z]{0,4}\.(?:[A-Za-z]{1,5}\.?)*|MBA|MSc|BSc|PhD|SE|SH|ST|MT|MM)$")


def _clean_person_name(display: str) -> str:
    # Bagian setelah koma dibuang hanya jika berupa gelar ("Budi, S.Kom., M.T.");
    # "Santoso, Budi" tetap utuh.
    parts = [p.strip() for p in display.split(",")]
    kept = [parts[0]] + [p for p in parts[1:]
                         if p and not all(_DEGREE_TOKEN_RE.match(t) for t in p.split())]
    name = " ".join(kept)
    name = re.sub(r"[\"()]|(?<![A-Za-z])'|'(?![A-Za-z])", " ", name)
    tokens = [t for t in re.split(r"\s+", name.strip()) if t]
    tokens = [t for t in tokens if t.rstrip(".").lower() not in _TITLE_TOKENS]
    return " ".join(tokens)


_SINGLE_ADDR_RE = re.compile(r'^\s*"?([^<>"]*?)"?\s*<([^<>\s]+@[^<>\s]+)>\s*$')


def parse_addresses(header_value: str | Iterable[str] | None) -> list[tuple[str, str]]:
    """Seperti email.utils.getaddresses, tetapi tahan terhadap nama tampilan
    tanpa kutip yang berisi koma (mis. `Budi Santoso, S.Kom. <budi@x.ac.id>`)."""
    if not header_value:
        return []
    values = [header_value] if isinstance(header_value, str) else list(header_value)
    out: list[tuple[str, str]] = []
    for value in values:
        try:   # =?UTF-8?B?...?= → teks biasa
            value = str(make_header(decode_header(value)))
        except Exception:  # header rusak: pakai apa adanya
            pass
        single = _SINGLE_ADDR_RE.match(value)
        if single and value.count("@") == 1:
            out.append((single.group(1).strip(), single.group(2).strip()))
        else:
            out.extend((d, a) for d, a in getaddresses([value]) if d or a)
    return out


def _neutralise(value: Any) -> Any:
    """Field yang tidak diredaksi tetap dinetralkan dari placeholder palsu."""
    if isinstance(value, str):
        return _INJECTED_PLACEHOLDER_RE.sub(NEUTRALISED_BRACKET, normalize_text(value))
    return value


def _name_key(name: str) -> str:
    return re.sub(r"[\s_.-]+", " ", name.strip().lower())


class PIIRedactor:
    """Satu instance per sesi/batch. Tabel pemetaan hanya di memori."""

    def __init__(self, keep_domain: bool = True, extra_names: Iterable[str] = ()) -> None:
        self.keep_domain = keep_domain
        self._counters = {"PERSON": 0, "EMAIL": 0, "PHONE": 0, "ACCOUNT": 0}
        self._by_value: dict[tuple[str, str], int] = {}
        self._originals: dict[tuple[str, int], str] = {}
        self._email_domain: dict[int, str] = {}
        self._full_names: dict[str, int] = {}          # nama lengkap (lower) -> nomor PERSON
        self._name_tokens: dict[str, int] = {}         # token nama (lower) -> nomor PERSON
        self._ambiguous_tokens: set[str] = set()
        self._name_re: re.Pattern[str] | None = None   # cache regex gabungan nama
        self._name_lookup: dict[str, int] = {}
        self.secrets_removed = 0
        for n in extra_names:
            self.register_person(n)

    def __repr__(self) -> str:  # jangan pernah tampilkan isi tabel
        counts = ", ".join(f"{k}={v}" for k, v in self._counters.items())
        return f"<PIIRedactor {counts}, secrets_removed={self.secrets_removed}>"

    # ------------------------------------------------------------------ util
    def _number_for(self, kind: str, key: str, original: str) -> int:
        k = (kind, key)
        if k not in self._by_value:
            self._counters[kind] += 1
            self._by_value[k] = self._counters[kind]
            self._originals[(kind, self._counters[kind])] = original
        return self._by_value[k]

    def _email_placeholder(self, address: str) -> str:
        address = address.strip()
        num = self._number_for("EMAIL", address.lower(), address)
        domain = address.rsplit("@", 1)[-1].lower()
        self._email_domain[num] = domain
        return f"<EMAIL_{num}@{domain}>" if self.keep_domain else f"<EMAIL_{num}>"

    def _secret(self) -> str:
        self.secrets_removed += 1
        return SECRET

    # ------------------------------------------------------------ registrasi
    def register_person(self, display_name: str, address: str | None = None) -> str | None:
        """Daftarkan nama orang (dari header atau preferensi). Mengembalikan placeholder."""
        if address:
            self._email_placeholder(address)
        name = _clean_person_name(display_name or "")
        if len(name) < 2 or not re.search(r"[A-Za-z]", name):
            return None
        # Nama pendek ("Rina") yang semua tokennya milik satu orang yang sudah dikenal
        # ("Rina Wulandari") memakai placeholder orang itu.
        tokens = [t.lower().strip(".") for t in name.split()]
        owners = {self._name_tokens.get(t) for t in tokens}
        if (name.lower() not in self._full_names and len(owners) == 1 and None not in owners
                and not any(t in self._ambiguous_tokens for t in tokens)):
            num = owners.pop()
            self._full_names[name.lower()] = num
            self._name_re = None
            return f"<PERSON_{num}>"
        num = self._number_for("PERSON", name.lower(), name)
        self._full_names.setdefault(name.lower(), num)
        self._name_re = None
        for tok in name.split():
            low = tok.lower().strip(".")
            if len(low) < 3 or low in _NAME_STOPWORDS:
                continue
            owner = self._name_tokens.get(low)
            if owner is None:
                self._name_tokens[low] = num
            elif owner != num:
                self._ambiguous_tokens.add(low)
        return f"<PERSON_{num}>"

    def register_header(self, header_value: str | Iterable[str] | None) -> None:
        for display, address in parse_addresses(header_value):
            local = address.split("@")[0] if "@" in address else ""
            is_org = bool(_ORG_HINTS.search(display)) or bool(_GENERIC_LOCALPARTS.match(local))
            if address and "@" in address:
                self._email_placeholder(address)
            if display and not is_org:
                self.register_person(display)

    # --------------------------------------------------------------- redaksi
    def redact_secrets(self, text: str) -> str:
        for pat in _SECRET_PATTERNS:
            text = pat.sub(lambda m: self._secret(), text)
        text = _BEARER_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{self._secret()}", text)
        labeled = lambda m: f"{m.group(1)}{m.group(2)}{self._secret()}"  # noqa: E731
        text = _PASSWORD_SECRET_RE.sub(labeled, text)
        text = _PASSWORD_INLINE_RE.sub(labeled, text)
        text = _TOKEN_SECRET_RE.sub(labeled, text)
        text = _OTP_SECRET_RE.sub(labeled, text)
        text = _BARE_KODE_RE.sub(labeled, text)
        text = _REVERSE_OTP_RE.sub(lambda m: self._secret(), text)
        text = _NIK_LABELED_RE.sub(
            lambda m: f"{m.group(1)}{m.group(2)}{self._secret()}" if len(_digits(m.group(3))) == 16
            else m.group(0), text)

        def card(m: re.Match[str]) -> str:
            digits = _digits(m.group(0))
            if nik_valid(digits):                      # NIK yang ditulis berkelompok
                return self._secret()
            if looks_like_card(digits) and not _id_context(m.string, m.start(), kind="card"):
                return self._secret()
            return m.group(0)
        text = _CARD_RE.sub(card, text)

        def nik(m: re.Match[str]) -> str:
            return self._secret() if nik_valid(m.group(0)) else m.group(0)
        return _SIXTEEN_DIGITS_RE.sub(nik, text)

    def _redact_emails(self, text: str) -> str:
        for m in _NAME_BEFORE_ADDR_RE.finditer(text):
            tokens, local = m.group(1).split(), m.group(2).split("@")[0].lower()
            # "Lihat Lampiran Rina <rina@x>": ambil mulai token pertama yang muncul di
            # bagian lokal alamat; jika tidak ada, ambil maksimal dua kata terakhir.
            start = next((i for i, t in enumerate(tokens) if t.lower() in local), max(0, len(tokens) - 2))
            self.register_header(f'"{" ".join(tokens[start:])}" <{m.group(2)}>')
        text = _sub_outside_placeholders(
            text, _BRACKETED_EMAIL_RE, lambda m: self._email_placeholder(m.group(1)))
        text = _sub_outside_placeholders(
            text, _EMAIL_URLENC_RE, lambda m: self._email_placeholder(unquote(m.group(0))))
        return _sub_outside_placeholders(
            text, _EMAIL_RE, lambda m: self._email_placeholder(m.group(0)))

    def _phone_placeholder(self, raw: str) -> str | None:
        key = _phone_key(raw)
        if key is None:
            return None
        return f"<PHONE_{self._number_for('PHONE', key, raw)}>"

    def _redact_phones(self, text: str) -> str:
        def repl(m: re.Match[str]) -> str:
            raw = m.group(0)
            if _id_context(m.string, m.start()):     # "NIM 0812...", "Resi 0812..."
                return raw
            # Jika regex ikut menelan angka di belakangnya ("0812 3456 7890 2026"),
            # buang kelompok terakhir satu per satu sampai nomornya valid.
            cand = raw
            while cand:
                ph = self._phone_placeholder(cand)
                if ph:
                    return ph + raw[len(cand):]
                shorter = _TRAILING_GROUP_RE.sub("", cand)
                if shorter == cand:
                    break
                cand = shorter
            return raw

        def wa(m: re.Match[str]) -> str:
            number = m.group(2)
            raw = number if number.startswith(("+", "0")) else "+" + number
            return m.group(1) + (self._phone_placeholder(raw) or number)
        text = _sub_outside_placeholders(text, _WHATSAPP_RE, wa)
        text = _sub_outside_placeholders(text, _MOBILE_RE, repl)
        return _sub_outside_placeholders(text, _LANDLINE_RE, repl)

    def _redact_accounts(self, text: str) -> str:
        def repl(m: re.Match[str]) -> str:
            num = self._number_for("ACCOUNT", _digits(m.group(3)), m.group(3))
            return f"{m.group(1)}{m.group(2)}<ACCOUNT_{num}>"
        return _sub_outside_placeholders(text, _ACCOUNT_RE, repl)

    def _discover_honorific_names(self, text: str) -> None:
        for m in _HONORIFIC_NAME_RE.finditer(text):
            tokens = []
            for tok in m.group(1).split():
                if tok.lower() in _NAME_STOPWORDS:
                    break
                tokens.append(tok)
            if tokens:
                self.register_person(" ".join(tokens))

    def _build_name_regex(self) -> None:
        """Satu regex gabungan untuk semua nama (cepat walau ada ratusan nama).

        Nama multi-kata: tidak peka huruf besar/kecil, pemisah spasi/_/./-.
        Nama satu kata dan token: wajib diawali huruf kapital ("Indah", bukan "indah"),
        dan token yang dipakai dua orang berbeda dilewati.
        """
        alts: list[str] = []
        lookup: dict[str, int] = {}
        for full, num in self._full_names.items():
            parts = full.split()
            if len(parts) > 1:
                alts.append("(?i:" + r"[\s_.-]+".join(map(re.escape, parts)) + ")")
            else:
                alts.append(r"(?=[^\W\d_])(?-i:[A-Z])(?i:" + re.escape(full[1:]) + ")"
                            if len(full) > 1 else re.escape(full))
            lookup[_name_key(full)] = num
        for tok, num in self._name_tokens.items():
            if tok in self._ambiguous_tokens or _name_key(tok) in lookup:
                continue
            alts.append(r"(?-i:[A-Z])(?i:" + re.escape(tok[1:]) + ")")
            lookup[_name_key(tok)] = num
        self._name_lookup = lookup
        if not alts:
            self._name_re = re.compile(r"(?!x)x")
            return
        alts.sort(key=len, reverse=True)
        self._name_re = re.compile(r"(?<![^\W_])(?:" + "|".join(alts) + r")(?![^\W_])")

    def _redact_names(self, text: str) -> str:
        if self._name_re is None:
            self._build_name_regex()
        assert self._name_re is not None

        def repl(m: re.Match[str]) -> str:
            num = self._name_lookup.get(_name_key(m.group(0)))
            return f"<PERSON_{num}>" if num is not None else m.group(0)
        return _sub_outside_placeholders(text, self._name_re, repl)

    def redact_text(self, text: Any) -> str:
        if text is None:
            return ""
        if isinstance(text, bytes):
            text = text.decode("utf-8", errors="replace")
        elif not isinstance(text, str):
            raise TypeError(f"redact_text butuh str atau bytes, bukan {type(text).__name__}")
        if not text:
            return ""
        text = normalize_text(text)
        text = _INJECTED_PLACEHOLDER_RE.sub(NEUTRALISED_BRACKET, text)
        text = self.redact_secrets(text)
        text = self._redact_emails(text)
        text = self._redact_accounts(text)
        text = self._redact_phones(text)
        self._discover_honorific_names(text)
        return self._redact_names(text)

    def redact_html(self, raw_html: str | None) -> str:
        return self.redact_text(html_to_text(raw_html or ""))

    def redact_attachment(self, attachment: dict[str, Any]) -> dict[str, Any]:
        """Hanya metadata: nama file (diredaksi), tipe, ukuran, dan penanda berisiko."""
        filename = attachment.get("filename") or ""
        lower = filename.lower()
        exts = re.findall(r"\.[a-z0-9]{1,5}", lower)
        risky = bool(exts) and (exts[-1] in RISKY_EXTENSIONS
                                or (len(exts) >= 2 and exts[-1] in RISKY_EXTENSIONS))
        return {
            # "_" diganti spasi agar nama/NIK di nama file seperti KTP_3174....jpg terdeteksi
            "filename": self.redact_text(filename.replace("_", " ")),
            "mime_type": _neutralise(attachment.get("mimeType") or attachment.get("mime_type") or ""),
            "size": attachment.get("size"),
            "risky": risky,
        }

    def redact_message(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Redaksi satu pesan. Kunci input: from, to, cc, subject, date,
        body_text atau body_html, attachments (list metadata)."""
        for key in ("from", "to", "cc"):
            self.register_header(msg.get(key))
        if msg.get("body_text"):
            body = self.redact_text(msg["body_text"])
        else:
            body = self.redact_html(msg.get("body_html"))
        return {
            "from": self.redact_header(msg.get("from")),
            "to": self.redact_header(msg.get("to")),
            "cc": self.redact_header(msg.get("cc")),
            "subject": self.redact_text(msg.get("subject")),
            "date": _neutralise(msg.get("date")),
            "body": body,
            "attachments": [self.redact_attachment(a) for a in msg.get("attachments") or []],
        }

    def redact_header(self, header_value: str | Iterable[str] | None) -> str:
        out = []
        for display, address in parse_addresses(header_value):
            parts = []
            if display:
                parts.append(self.redact_text(display))
            if address:
                parts.append(self._email_placeholder(address) if "@" in address
                             else self.redact_text(address))
            out.append(" ".join(parts))
        return ", ".join(out)

    # -------------------------------------------------------------- pemulihan
    def restore(self, text: str) -> str:
        """Kembalikan placeholder ke nilai asli (dipakai tepat sebelum aksi dijalankan).
        `[SECRET]` dan placeholder yang tidak dikenal dibiarkan apa adanya."""
        def repl(m: re.Match[str]) -> str:
            original = self._lookup(m)
            return original if original is not None else m.group(0)
        return PLACEHOLDER_RE.sub(repl, text)

    def _lookup(self, m: re.Match[str]) -> str | None:
        """Nilai asli untuk satu placeholder, atau None bila tidak dikenal.
        Placeholder email dengan domain yang tidak cocok dianggap tidak dikenal."""
        if m.group(0) == SECRET:
            return None
        kind, num, dom = m.group("kind"), int(m.group("num")), m.group("dom")
        if dom is not None and (kind != "EMAIL" or self._email_domain.get(num) != dom.lower()):
            return None
        return self._originals.get((kind, num))

    def unknown_placeholders(self, text: str) -> list[str]:
        """Placeholder di teks LLM yang tidak ada di tabel (indikasi halusinasi/injeksi)."""
        return [m.group(0) for m in PLACEHOLDER_RE.finditer(text)
                if m.group(0) != SECRET and self._lookup(m) is None]

    def leaked_values(self, text: str) -> list[str]:
        """Nilai asli yang masih muncul di teks (untuk metrik kebocoran PII Fase 5)."""
        low = text.lower()
        return sorted({v for v in self._originals.values() if len(v) >= 3 and v.lower() in low})

    def clear(self) -> None:
        """Hapus tabel pemetaan dari memori (panggil di akhir sesi)."""
        self.__init__(keep_domain=self.keep_domain)


# ---------------------------------------------------------- kontrak 3
# Antarmuka fungsi yang dipakai B, A, dan D (lihat app/contracts.py).
# Hanya meneruskan ke PIIRedactor; logika redaksi tetap di kelas di atas.

PiiMap = PIIRedactor

_pii_maps: dict[str, PIIRedactor] = {}   # satu peta per batch, hanya di memori


def pii_map_for(batch_id: str) -> PiiMap:
    """Peta PII untuk batch ini; panggilan berulang memberi peta yang sama.

    keep_domain=False: placeholder email berbentuk <EMAIL_n> sesuai kontrak,
    karena domain pengirim sudah tersedia lewat from_domain.
    """
    pii_map = _pii_maps.get(batch_id)
    if pii_map is None:
        pii_map = _pii_maps[batch_id] = PIIRedactor(keep_domain=False)
    return pii_map


def release_pii_map(batch_id: str) -> None:
    """Hapus peta batch dari memori (panggil setelah report selesai)."""
    pii_map = _pii_maps.pop(batch_id, None)
    if pii_map is not None:
        pii_map.clear()


def redact(text: str, pii_map: PiiMapProtocol) -> str:
    return pii_map.redact_text(text)


def restore(text: str, pii_map: PiiMapProtocol) -> str:
    return pii_map.restore(text)
