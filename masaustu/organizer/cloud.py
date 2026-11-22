"""Bulut (Firebase) hesabı ve arka planda eşitleme."""
from datetime import datetime

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (QDialog, QFormLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QHBoxLayout, QVBoxLayout)

from .db import Database
from .i18n import t
from .sync import FirebaseClient, SyncError, parse_config, sync

# v.1.0.10: Programla gelen ortak Firebase projesi KALDIRILDI — herkes kendi ücretsiz Firebase hesabını kullanır
# (yöneticinin günlük sınırı başkalarınca harcanmasın). Kurulum rehberi: REHBER.
DEFAULT_FB_CONFIG = ""
REHBER = "https://github.com/departures-mil/duyurular/blob/main/firebase-kurulum.md"
# Eski ortak projeye bağlı tek hesap (yönetici) ayarı kendi ayarı olarak saklanır; diğer cihazların bağlantısı kesilir.
_ESKI_ORTAK = """const firebaseConfig = {
  apiKey: "AIzaSyDWK8jDUdNW0k3vwHDbNBgud6gTEIdqhcg",
  authDomain: "duzenli-evim.firebaseapp.com",
  projectId: "duzenli-evim",
  storageBucket: "duzenli-evim.firebasestorage.app",
  messagingSenderId: "1059030151497",
  appId: "1:1059030151497:web:0e320562bdc00ff4a7aa98"
};"""
_YONETICI = "yonetici@example.invalid"


def ortak_projeden_tasi(db):
    """fb_config boşken eski ortak projeye bağlı kurulumları ayarlar: yönetici aynen devam eder, diğerleri kendi hesabını kurar."""
    if db.get_setting("fb_config") or not db.get_setting("fb_refresh"):
        return
    if (db.get_setting("fb_email", "") or "").strip().lower() == _YONETICI:
        db.set_setting("fb_config", _ESKI_ORTAK)
    else:
        db.set_setting("fb_refresh", "")
        db.set_setting("fb_ortak_kesildi", "1")


AUTO_INTERVAL_MS = 3 * 60 * 1000


def error_text(e: SyncError):
    msg = (e.detail or "").upper()
    if e.code == "config":
        return t("Firebase ayarları okunamadı. Konsoldaki firebaseConfig bölümünü olduğu gibi yapıştırın.")
    if e.code == "network":
        return t("İnternete ya da Firebase'e bağlanılamadı.")
    if "EMAIL_EXISTS" in msg:
        return t("Bu e-posta ile zaten bir hesap var. „Giriş yap“ı kullanın.")
    if "WEAK_PASSWORD" in msg:
        return t("Şifre en az 6 karakter olmalı.")
    if "INVALID" in msg or "EMAIL_NOT_FOUND" in msg or "PASSWORD" in msg:
        return t("E-posta ya da şifre hatalı.")
    if "OPERATION_NOT_ALLOWED" in msg or "CONFIGURATION_NOT_FOUND" in msg:
        return t("Firebase'de e-posta/şifre ile giriş açılmamış (Authentication › Sign-in method).")
    if "PERMISSION" in msg or e.code == "auth":
        return t("Firebase izin vermedi. Firestore kurallarını talimattaki gibi ayarlayın.")
    if "NOT_FOUND" in msg or "DATABASE" in msg:
        return t("Firestore veritabanı bulunamadı. Firebase'de Firestore Database oluşturun.")
    return t("Eşitleme hatası: {m}", m=e.detail or e.code)


class _Worker(QThread):
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, data_dir, config, refresh_token):
        super().__init__()
        self.data_dir, self.config, self.refresh_token = data_dir, config, refresh_token
        self.new_refresh = None

    def run(self):
        try:
            db = Database(self.data_dir)
            client = FirebaseClient(self.config)
            client.resume(self.refresh_token)
            result = sync(db, client)
            self.new_refresh = client.refresh_token
            db.conn.close()
            self.done.emit(result)
        except SyncError as e:
            self.failed.emit(error_text(e))
        except Exception as e:  # beklenmeyen hata programı düşürmesin
            self.failed.emit(t("Eşitleme hatası: {m}", m=str(e)))


class SyncManager(QObject):
    """Giriş bilgilerini saklar, eşitlemeyi arka planda çalıştırır."""
    state_changed = Signal(str)   # durum metni
    data_changed = Signal()       # buluttan yeni veri geldi

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        try:
            ortak_projeden_tasi(db)
        except Exception:
            pass
        self.worker = None
        self.last_error = ""
        self.timer = QTimer(self, interval=AUTO_INTERVAL_MS)
        self.timer.timeout.connect(self.sync_now)
        self.timer.start()

    # ------------------------------------------------------------ durum
    def config(self):
        raw = self.db.get_setting("fb_config") or DEFAULT_FB_CONFIG
        try:
            return parse_config(raw) if raw else None
        except SyncError:
            return None

    def is_connected(self):
        return bool(self.config() and self.db.get_setting("fb_refresh"))

    def email(self):
        return self.db.get_setting("fb_email", "")

    def busy(self):
        return self.worker is not None and self.worker.isRunning()

    def status_text(self):
        if not self.is_connected():
            if self.db.get_setting("fb_ortak_kesildi") == "1":
                return t("Artık herkes kendi ücretsiz Firebase hesabını kullanıyor. Bulut hesabı bölümünden kendi hesabınızı bağlayın.")
            return t("Bulut hesabı bağlı değil")
        if self.busy():
            return t("Eşitleniyor…")
        if self.last_error:
            return "⚠ " + self.last_error
        last = self.db.get_setting("sync_last")
        return t("Son eşitleme: {d}", d=last) if last else t("Henüz eşitlenmedi")

    # ------------------------------------------------------------ hesap
    def connect_account(self, config_text, email, password, create):
        config = parse_config(config_text)
        client = FirebaseClient(config)
        client.sign_in(email.strip(), password, create=create)
        if self.db.get_setting("fb_uid") != client.uid:
            self.db.reset_sync_state()
        self.db.set_setting("fb_config", config_text.strip())
        self.db.set_setting("fb_email", client.email or email.strip())
        self.db.set_setting("fb_refresh", client.refresh_token)
        self.db.set_setting("fb_uid", client.uid)
        self.last_error = ""
        self.state_changed.emit(self.status_text())

    def disconnect_account(self):
        for k in ("fb_refresh", "fb_email"):
            self.db.set_setting(k, None)
        self.state_changed.emit(self.status_text())

    # ------------------------------------------------------------ eşitleme
    def sync_now(self):
        if not self.is_connected() or self.busy():
            return
        self.worker = _Worker(self.db.data_dir, self.config(), self.db.get_setting("fb_refresh"))
        self.worker.done.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.start()
        self.state_changed.emit(self.status_text())

    def _done(self, result):
        if self.worker and self.worker.new_refresh:
            self.db.set_setting("fb_refresh", self.worker.new_refresh)
        self.db.set_setting("sync_last", datetime.now().strftime("%d.%m.%Y %H:%M"))
        self.last_error = ""
        self.state_changed.emit(self.status_text())
        if result.get("received"):
            self.data_changed.emit()

    def _failed(self, text):
        self.last_error = text
        self.state_changed.emit(self.status_text())

    def finish(self, timeout_ms=20000):
        """Kapanırken: gönderilmemiş değişiklik varsa son bir kez eşitle."""
        if self.busy():
            self.worker.wait(timeout_ms)
        if self.is_connected() and any(self.db.dirty_records().values()):
            self.sync_now()
            if self.worker:
                self.worker.wait(timeout_ms)


class AccountDialog(QDialog):
    def __init__(self, manager: SyncManager, parent=None):
        super().__init__(parent)
        self.m = manager
        self.setWindowTitle(t("Bulut hesabı (Firebase)"))
        self.setMinimumWidth(640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        title = QLabel(t("Bulut hesabı (Firebase)"))
        title.setObjectName("PageTitle")
        lay.addWidget(title)
        hint = QLabel(t("Telefon ve bilgisayarda aynı Firebase ayarlarını ve aynı e-posta/şifreyi kullanın. "
                        "Böylece iki cihaz aynı arşivi görür."))
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        hint2 = QLabel(t("Eşitleme kendi ücretsiz Firebase hesabınızla yapılır; kayıtlarınız ve günlük sınırınız yalnızca size aittir.")
                       + f' <a href="{REHBER}">' + t("Kendi Firebase hesabınızı kurun (rehber)") + "</a>")
        hint2.setWordWrap(True)
        hint2.setOpenExternalLinks(True)
        lay.addWidget(hint2)
        form = QFormLayout()
        form.setVerticalSpacing(10)
        self.config = QPlainTextEdit(self.m.db.get_setting("fb_config", "") or DEFAULT_FB_CONFIG)
        self.config.setPlaceholderText('const firebaseConfig = {\n  apiKey: "…",\n  projectId: "…",\n  …\n};')
        self.config.setFixedHeight(130)
        self.config.setLayoutDirection(Qt.LeftToRight)
        self.email = QLineEdit(self.m.email())
        self.email.setPlaceholderText("ornek@gmail.com")
        self.email.setLayoutDirection(Qt.LeftToRight)
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        form.addRow(t("Firebase ayarları:"), self.config)
        form.addRow(t("E-posta:"), self.email)
        form.addRow(t("Şifre:"), self.password)
        lay.addLayout(form)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: #c0392b; font-weight: 600;")
        lay.addWidget(self.message)
        row = QHBoxLayout()
        create = QPushButton(t("Yeni hesap oluştur"))
        create.clicked.connect(lambda: self._go(True))
        login = QPushButton(t("Giriş yap"))
        login.setObjectName("Primary")
        login.clicked.connect(lambda: self._go(False))
        close = QPushButton(t("Kapat"))
        close.clicked.connect(self.reject)
        row.addWidget(create)
        row.addStretch()
        row.addWidget(close)
        row.addWidget(login)
        lay.addLayout(row)

    def _go(self, create):
        if not self.email.text().strip() or not self.password.text():
            self.message.setText(t("E-posta ve şifreyi yazın."))
            return
        self.message.setStyleSheet("color: #2a9d8f; font-weight: 600;")
        self.message.setText(t("Bağlanıyor…"))
        self.repaint()
        try:
            self.m.connect_account(self.config.toPlainText(), self.email.text(), self.password.text(), create)
        except SyncError as e:
            self.message.setStyleSheet("color: #c0392b; font-weight: 600;")
            self.message.setText(error_text(e))
            return
        self.accept()
        self.m.sync_now()
