import re
import os
import json
import threading
from aqt import mw
from aqt.qt import *
from aqt import gui_hooks
from aqt.utils import showInfo, tooltip

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
except ImportError:
    from aqt.qt import QWebEngineView

HAS_PYNPUT = False
try:
    from pynput import keyboard

    HAS_PYNPUT = True
except ImportError:
    import subprocess
    import sys

    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pynput"])
        from pynput import keyboard

        HAS_PYNPUT = True
    except:
        pass

_live_conf = None


def get_config():
    global _live_conf
    if _live_conf: return _live_conf
    default = {
        "deck_maps": [],
        "width": 600, "height": 300, "opacity": 90,
        "pos_x": 50, "pos_y": 50,
        "color_word": "#ff79c6", "color_pitch": "#50fa7b", "color_sent": "#bd93f9",
        "key_again": "1", "key_hard": "2", "key_good": "3", "key_easy": "4",
        "key_flip": "<caps_lock>", "key_replay": "5", "key_undo": "<delete>", "key_toggle": "<ctrl>+<shift>+o"
    }
    conf = mw.addonManager.getConfig(__name__)
    if not conf:
        _live_conf = default
        return default
    for k, v in default.items():
        if k not in conf: conf[k] = v
    _live_conf = conf
    return conf


# Record Hotkeys
class HotkeyRecorder(QPushButton):
    def __init__(self, current_key, parent=None):
        super().__init__(current_key if current_key else "None", parent)
        self.current_key = current_key
        self.recording = False
        self.setFixedWidth(150)
        self.setCheckable(True)
        self.clicked.connect(self.toggle_recording)

    def toggle_recording(self):
        if self.isChecked():
            self.recording = True
            self.setText("... ? ...")
            self.setFocus()
        else:
            self.recording = False
            self.setText(self.current_key if self.current_key else "None")

    def keyPressEvent(self, event):
        if not self.recording: return super().keyPressEvent(event)
        key = event.key()
        if key in [Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta]: return
        mod = event.modifiers()
        parts = []
        if mod & Qt.KeyboardModifier.ControlModifier: parts.append("<ctrl>")
        if mod & Qt.KeyboardModifier.ShiftModifier: parts.append("<shift>")
        if mod & Qt.KeyboardModifier.AltModifier: parts.append("<alt>")
        if mod & Qt.KeyboardModifier.MetaModifier: parts.append("<meta>")
        key_str = QKeySequence(key).toString().lower()
        mapping = {"backspace": "<backspace>", "del": "<delete>", "ins": "<insert>", "return": "<enter>",
                   "enter": "<enter>", "capslock": "<caps_lock>"}
        parts.append(mapping.get(key_str, key_str))
        self.current_key = "+".join(parts)
        self.setText(self.current_key)
        self.recording = False
        self.setChecked(False)


# overlay window
class Overlay(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.main_layout = QVBoxLayout()
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(8)
        self.web_text = QWebEngineView();
        self.web_image = QWebEngineView();
        self.web_sentence = QWebEngineView()
        for w in [self.web_text, self.web_image, self.web_sentence]:
            w.page().setBackgroundColor(Qt.GlobalColor.transparent)
            w.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
            self.main_layout.addWidget(w)
        self.setLayout(self.main_layout)
        self.apply_prefs()
        self.show()

    def apply_prefs(self):
        conf = get_config()
        self.fixed_width = conf["width"]
        self.max_def_height = conf["height"]
        self.move(conf["pos_x"], conf["pos_y"])
        self.update_geometry(False, False, False)

    def update_geometry(self, is_answer, has_image, has_sentence):
        self.web_text.setFixedHeight(self.max_def_height if is_answer else 110)
        total_h = self.web_text.height()
        if has_image and is_answer:
            img_h = int(self.fixed_width * 0.6)
            self.web_image.setFixedHeight(img_h);
            self.web_image.show()
            total_h += img_h + 8
        else:
            self.web_image.hide()
        if has_sentence and is_answer:
            sent_h = 90
            self.web_sentence.setFixedHeight(sent_h);
            self.web_sentence.show()
            total_h += sent_h + 8
        else:
            self.web_sentence.hide()
        self.setFixedSize(self.fixed_width, total_h)

    def set_content(self, html_body, image_html="", sentence_html="", card_css="", is_answer=False):
        conf = get_config()
        alpha = conf["opacity"] / 100.0
        media_url = QUrl.fromLocalFile(mw.col.media.dir() + os.path.sep).toString()
        style = f"""
        <style>
        {card_css}
        html, body {{ background: transparent !important; margin: 0; padding: 0; color: white; font-family: sans-serif; height: 100%; width: 100%; overflow: hidden; }}
        .box {{ background: rgba(12, 12, 12, {alpha}); border: 2px solid rgba(255,255,255,0.15); border-radius: 18px; height: 100%; display: flex; flex-direction: column; box-sizing: border-box; }}
        .content-area {{ width: 100%; text-align: center; padding: 12px; box-sizing: border-box; overflow-y: auto; flex-grow: 1; display: flex; flex-direction: column; {"justify-content: center;" if not is_answer else "justify-content: flex-start;"} }}
        .content-area::-webkit-scrollbar {{ width: 0px; background: transparent; }}
        img {{ max-width: 100%; height: auto; border-radius: 10px; margin: auto; display: block; }}
        .word-text {{ font-size: 3.2em; font-weight: bold; color: {conf['color_word']}; line-height: 1.1; }}
        .pitch-accent {{ color: {conf['color_pitch']}; font-size: 1.2em; margin-bottom: 4px; }}
        .sentence-text {{ font-style: italic; color: {conf['color_sent']}; font-size: 1.1em; }}
        hr {{ border: 0; border-top: 1px solid rgba(255,255,255,0.1); margin: 8px auto; width: 80%; }}
        </style>
        """
        self.update_geometry(is_answer, bool(image_html), bool(sentence_html))
        f_path = QUrl.fromLocalFile(mw.col.media.dir() + os.path.sep)
        self.web_text.setHtml(
            f"<html><head><base href='{media_url}'>{style}</head><body><div class='box'><div class='content-area'>{html_body}</div></div></body></html>",
            f_path)
        self.web_image.setHtml(
            f"<html><head><base href='{media_url}'>{style}</head><body><div class='box'><div class='content-area'>{image_html}</div></div></body></html>",
            f_path)
        self.web_sentence.setHtml(
            f"<html><head><base href='{media_url}'>{style}</head><body><div class='box'><div class='content-area'><div class='sentence-text'>{sentence_html}</div></div></div></body></html>",
            f_path)

    def toggle_visibility(self):
        if self.isVisible():
            self.hide()
            if mw.state == "review":
                mw.moveToState("overview")
        else:
            self.show()
            self.raise_()
            if mw.state in ["overview", "deckBrowser"]:
                mw.onStudyKey()
        mw.activateWindow()


overlay = None
current_listener = None


# core
def update_overlay():
    if not overlay: return
    QTimer.singleShot(100, _force_refresh_data)


def _force_refresh_data():
    if mw.state != "review" or not mw.reviewer.card:
        overlay.set_content("<div class='word-text' style='opacity:0.3;'>Standby</div>")
        return
    card = mw.reviewer.card;
    note = card.note();
    conf = get_config()
    deck_name = mw.col.decks.get(card.did)['name']
    deck_cfg = next((m for m in conf.get("deck_maps", []) if m['deck'] == deck_name), None)
    if not deck_cfg:
        overlay.set_content("Deck Not Mapped")
        return
    is_ans = (mw.reviewer.state == "answer")

    def get_f(k):
        fn = deck_cfg.get(k)
        return mw.col.media.escape_media_filenames(note[fn]) if (fn and fn in note) else ""

    word_html = f'<div class="word-text">{get_f("word")}</div>'
    if is_ans:
        word_html += f'<div class="pitch-accent">{get_f("pitch")}</div>'
        if get_f("definition"): word_html += f"<hr><div>{get_f('definition')}</div>"
    overlay.set_content(word_html, get_f("image") if is_ans else "", get_f("sentence") if is_ans else "",
                        note.model()['css'], is_ans)


def start_global_listener():
    global current_listener
    if not HAS_PYNPUT: return
    if current_listener: current_listener.stop()
    c = get_config()

    def safe_run(f, *a):
        return lambda: mw.taskman.run_on_main(lambda: f(*a) if (mw.state == "review" and mw.reviewer.card) else None)

    hotkeys = {
        c['key_toggle']: lambda: mw.taskman.run_on_main(overlay.toggle_visibility),
        c['key_replay']: safe_run(mw.reviewer.replayAudio),
        c['key_undo']: safe_run(mw.onUndo),
        c['key_flip']: safe_run(lambda: mw.reviewer._showAnswer() if mw.reviewer.state == "question" else None),
        c['key_again']: safe_run(mw.reviewer._answerCard, 1),
        c['key_hard']: safe_run(mw.reviewer._answerCard, 2),
        c['key_good']: safe_run(mw.reviewer._answerCard, 3),
        c['key_easy']: safe_run(mw.reviewer._answerCard, 4),
    }
    try:
        current_listener = keyboard.GlobalHotKeys(hotkeys)
        current_listener.daemon = True
        current_listener.start()
    except:
        pass


# Config Dialog
class ConfigDialog(QDialog):
    def __init__(self):
        super().__init__(mw);
        self.setWindowTitle("Overlay Preferences");
        self.resize(900, 600)
        self.conf = get_config();
        self.all_decks = sorted(mw.col.decks.all_names())
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self);
        tabs = QTabWidget()

        # Mapping Tab
        deck_w = QWidget();
        dvl = QVBoxLayout(deck_w)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Deck", "Word", "Pitch", "Def", "Sentence", "Image"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for m in self.conf.get("deck_maps", []): self._add_row(m)
        btns = QHBoxLayout()
        add_b = QPushButton("+ Add Mapping");
        add_b.clicked.connect(lambda: self._add_row({}))
        rem_b = QPushButton("- Remove Selected");
        rem_b.clicked.connect(lambda: self.table.removeRow(self.table.currentRow()))
        btns.addWidget(add_b);
        btns.addWidget(rem_b)
        dvl.addWidget(self.table);
        dvl.addLayout(btns)
        tabs.addTab(deck_w, "Decks Mapping")

        # Visuals Tab
        gen = QWidget();
        glayout = QFormLayout(gen)
        self.w = QSpinBox();
        self.w.setRange(200, 2500);
        self.w.setValue(self.conf['width'])
        self.h = QSpinBox();
        self.h.setRange(100, 2000);
        self.h.setValue(self.conf['height'])
        self.op = QSlider(Qt.Orientation.Horizontal);
        self.op.setRange(0, 100);
        self.op.setValue(self.conf['opacity'])
        self.c_w = QLineEdit(self.conf['color_word']);
        self.c_p = QLineEdit(self.conf['color_pitch']);
        self.c_s = QLineEdit(self.conf['color_sent'])
        glayout.addRow("Width:", self.w);
        glayout.addRow("Answer Box Height:", self.h);
        glayout.addRow("Opacity %:", self.op)
        glayout.addRow("Word Color:", self.c_w);
        glayout.addRow("Pitch Color:", self.c_p);
        glayout.addRow("Sentence Color:", self.c_s)
        tabs.addTab(gen, "Visuals")

        # Hotkeys Tab
        keys_w = QWidget();
        klayout = QFormLayout(keys_w)
        self.hk_widgets = {}
        for k in ['key_toggle', 'key_flip', 'key_replay', 'key_undo', 'key_again', 'key_hard', 'key_good', 'key_easy']:
            rec = HotkeyRecorder(self.conf.get(k, ""));
            self.hk_widgets[k] = rec
            klayout.addRow(k.replace("key_", "").title() + ":", rec)
        tabs.addTab(keys_w, "Hotkeys")

        layout.addWidget(tabs)
        btn = QPushButton("Save & Apply Settings");
        btn.clicked.connect(self.save_all);
        layout.addWidget(btn)

    def _add_row(self, data):
        r = self.table.rowCount();
        self.table.insertRow(r)
        deck_cb = QComboBox();
        deck_cb.addItems(["Select Deck..."] + self.all_decks)
        combos = [QComboBox() for _ in range(5)]

        def update_f():
            name = deck_cb.currentText()
            fields = self._get_f(name) if name != "Select Deck..." else []
            for c in combos:
                old = c.currentText();
                c.clear();
                c.addItems([""] + fields)
                if old in fields: c.setCurrentText(old)

        deck_cb.currentIndexChanged.connect(update_f)
        self.table.setCellWidget(r, 0, deck_cb)
        for i, c in enumerate(combos): self.table.setCellWidget(r, i + 1, c)
        if data.get("deck"):
            deck_cb.setCurrentText(data["deck"]);
            update_f()
            keys = ["word", "pitch", "definition", "sentence", "image"]
            for i, k in enumerate(keys):
                if data.get(k): combos[i].setCurrentText(data[k])

    def _get_f(self, name):
        try:
            did = mw.col.decks.id(name);
            mids = mw.col.db.list("select distinct n.mid from cards c join notes n on c.nid = n.id where c.did = ?",
                                  did)
            fields = set()
            for mid in mids:
                model = mw.col.models.get(mid)
                if model: [fields.add(f['name']) for f in model['flds']]
            return sorted(list(fields))
        except:
            return []

    def save_all(self):
        global _live_conf
        new_maps = []
        for r in range(self.table.rowCount()):
            d_cb = self.table.cellWidget(r, 0)
            if d_cb and d_cb.currentText() != "Select Deck...":
                new_maps.append({
                    "deck": d_cb.currentText(), "word": self.table.cellWidget(r, 1).currentText(),
                    "pitch": self.table.cellWidget(r, 2).currentText(),
                    "definition": self.table.cellWidget(r, 3).currentText(),
                    "sentence": self.table.cellWidget(r, 4).currentText(),
                    "image": self.table.cellWidget(r, 5).currentText()
                })
        final = {
            "deck_maps": new_maps, "width": self.w.value(), "height": self.h.value(), "opacity": self.op.value(),
            "color_word": self.c_w.text(), "color_pitch": self.c_p.text(), "color_sent": self.c_s.text(),
            "pos_x": self.conf.get("pos_x", 50), "pos_y": self.conf.get("pos_y", 50)
        }
        for k, w in self.hk_widgets.items(): final[k] = w.current_key
        mw.addonManager.writeConfig(__name__, final)
        _live_conf = final
        overlay.apply_prefs();
        start_global_listener();
        self.accept()


def on_profile_open():
    global overlay
    QTimer.singleShot(1000, lambda: globals().update(overlay=Overlay()) or start_global_listener())
    act = QAction("Overlay Settings", mw);
    act.triggered.connect(lambda: ConfigDialog().exec());
    mw.form.menuTools.addAction(act)


gui_hooks.profile_did_open.append(on_profile_open)
gui_hooks.reviewer_did_show_question.append(lambda card: update_overlay())
gui_hooks.reviewer_did_show_answer.append(lambda card: update_overlay())