import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tempfile
import unittest
from unittest.mock import patch
from PyQt6.QtWidgets import QApplication
from clipper.app import Window

class InterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
    def test_window_lists_clip_and_filters(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            path = Path(d) / 'test.mp4'; path.touch()
            window = Window()
            window.folder = d; window.refresh()
            self.assertEqual(window.list.count(), 1)
            window.search.setText('missing')
            self.assertEqual(window.list.count(), 0)
            window.quitting = True; window.close()

    def test_gallery_card_size_tracks_window_width(self):
        from pathlib import Path
        from PyQt6.QtWidgets import QSizePolicy
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            (Path(d) / 'responsive.mp4').touch()
            window = Window(); window.folder = d; window.refresh(); window.show()
            window.resize(1500, 850); self.application.processEvents(); window.update_grid_size()
            wide = window.list.itemDelegate().sizeHint(None, window.list.model().index(0, 0)).width()
            window.resize(1000, 700); self.application.processEvents(); window.update_grid_size()
            narrow = window.list.itemDelegate().sizeHint(None, window.list.model().index(0, 0)).width()
            self.assertGreater(wide, narrow)
            window.quitting = True; window.close()

    def test_gallery_cards_fit_after_opening_details_and_resizing(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            for i in range(4): (Path(d) / f'clip{i}.mp4').touch()
            window = Window(); window.folder = d
            with patch.object(window.thumbnails, 'request', return_value=None):
                window.refresh(); window.resize(1000, 700); window.show(); self.application.processEvents()
                window.list.setCurrentItem(window.list.item(0)); window.list.item(0).setSelected(True)
                self.application.processEvents(); window.update_grid_size(); window.list.doItemsLayout(); self.application.processEvents()
                self.assertTrue(window.details_panel.isVisible())
                viewport = window.list.viewport().rect()
                for i in range(window.list.count()):
                    rect = window.list.visualItemRect(window.list.item(i))
                    self.assertGreaterEqual(rect.left(), viewport.left())
                    self.assertLessEqual(rect.right(), viewport.right())
                self.assertLessEqual(window.list.gridSize().width(), viewport.width())
            window.quitting = True; window.close()

    def test_single_gallery_click_selects_and_reveals_clip_actions(self):
        from pathlib import Path
        from PyQt6.QtCore import Qt
        from PyQt6.QtTest import QTest
        from PyQt6.QtWidgets import QPushButton
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            (Path(d) / 'selectable.mp4').touch()
            window = Window(); window.folder = d; window.refresh(); window.resize(1500, 760); window.show()
            self.application.processEvents()
            item = window.list.item(0); rect = window.list.visualItemRect(item)
            QTest.mouseClick(window.list.viewport(), Qt.MouseButton.LeftButton, pos=rect.center())
            self.application.processEvents()
            self.assertTrue(window.details_panel.isVisible())
            self.assertEqual(window.detail_title.text(), 'selectable')
            self.assertGreater(window.list.viewport().width(), 0)
            self.assertTrue(window.list.visualItemRect(item).isValid())
            window.resize(1000, 700); self.application.processEvents(); window.update_grid_size()
            self.assertGreater(window.list.viewport().width(), 0)
            self.assertLessEqual(window.list.gridSize().width(), window.list.viewport().width())
            self.assertIsNone(window.active_editor)
            self.assertTrue(any(button.text() == 'Otevřít editor' for button in window.details_panel.findChildren(QPushButton)))
            window.list.clearSelection(); self.application.processEvents()
            self.assertTrue(window.details_panel.isHidden())
            window.quitting = True; window.close()

    def test_thumbnail_failure_and_recovery_update_card_and_details(self):
        from pathlib import Path
        from PyQt6.QtCore import Qt
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            clip = Path(d) / 'clip.mp4'; clip.touch()
            window = Window(); window.folder = d; window.refresh()
            item = window.list.item(0); window.detail_path = clip
            window.thumbnail_failed(str(clip))
            self.assertTrue(item.data(Qt.ItemDataRole.UserRole + 5))
            self.assertEqual(window.detail_thumbnail.text(), 'Náhled není dostupný')
            window.thumbnail_ready(str(clip), str(Path(d) / 'missing.jpg'))
            self.assertFalse(item.data(Qt.ItemDataRole.UserRole + 5))
            window.quitting = True; window.close()

    def test_editor_video_surface_shows_thumbnail_before_first_decoded_frame(self):
        from PyQt6.QtGui import QColor, QImage, QPixmap
        from clipper.editor import VideoSurface
        surface = VideoSurface(); surface.resize(320, 180)
        poster = QImage(16, 9, QImage.Format.Format_RGB32); poster.fill(QColor('#ff7300'))
        surface.set_poster(QPixmap.fromImage(poster))
        surface.show(); self.application.processEvents()
        rendered = surface.grab().toImage()
        self.assertEqual(rendered.pixelColor(160, 90), QColor('#ff7300'))
        surface.close()

    def test_real_editor_opens_inside_main_window_with_timeline(self):
        from pathlib import Path
        from PyQt6.QtCore import QObject, pyqtSignal
        from unittest.mock import patch
        import clipper.editor as editor_module
        class AudioPreviewStub(QObject):
            failed = pyqtSignal(str); status = pyqtSignal(str)
            def __init__(self, *args): super().__init__()
            def close(self): pass
            def set_first_is_mix(self, *args): pass
            def set_gain(self, *args): pass
            def set_master(self, *args): pass
            def set_muted(self, *args): pass
        info = {'streams':[{'codec_type':'video','index':0,'duration':'4','codec_name':'h264','avg_frame_rate':'30/1'}], 'format':{'duration':'4'}}
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            clip = Path(d) / 'embedded.mp4'; clip.touch()
            window = Window()
            with patch.object(editor_module, 'AudioPreview', AudioPreviewStub):
                window.show_editor(clip, info)
                self.assertIsNotNone(window.active_editor)
                self.assertFalse(window.active_editor.isWindow())
                self.assertTrue(window.tabs.isHidden())
                self.assertIsNotNone(window.active_editor.video_timeline)
                window.active_editor.reject()
            self.assertIsNone(window.active_editor)
            self.assertFalse(window.tabs.isHidden())
            window.quitting = True; window.close()

    def test_quitting_closes_editor_and_saves_its_selection(self):
        from pathlib import Path
        from clipper.library import Library
        info = {'streams':[{'codec_type':'video','index':0,'duration':'4','codec_name':'h264','avg_frame_rate':'30/1'}], 'format':{'duration':'4'}}
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            clip = Path(d) / 'clip.mp4'; clip.touch()
            window = Window(); window.show_editor(clip, info)
            editor = window.active_editor
            self.assertIsNotNone(editor)
            editor.start.setValue(1.0)
            database = window.data_path / 'library.sqlite3'
            window.quitting = True; window.close()
            self.assertTrue(editor.closing)
            self.assertIsNone(window.active_editor)
            reopened = Library(database)
            try: self.assertAlmostEqual(reopened.edit_for(clip)['in'], .25)
            finally: reopened.close()

    def test_quitting_waits_for_screen_preview_worker(self):
        from PyQt6.QtCore import QEventLoop, QThread, QTimer
        class SlowPreview(QThread):
            def run(self): self.msleep(200)
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            window = Window(); window.show(); window.quitting = True
            worker = SlowPreview(window); window.screen_preview_worker = worker; worker.start()
            self.assertFalse(window.close())
            self.assertFalse(window.preview_timer.isActive())
            loop = QEventLoop(); QTimer.singleShot(600, loop.quit); loop.exec()
            self.assertFalse(worker.isRunning())
            self.assertFalse(window.isVisible())

    def test_finished_screen_previews_are_released(self):
        import sys
        if not sys.platform.startswith('linux'): self.skipTest('Linux screen preview')
        from PyQt6 import sip
        from PyQt6.QtCore import QObject, QCoreApplication, QEvent, pyqtSignal
        class FakeScreenJob(QObject):
            frame = pyqtSignal(bytes); failed = pyqtSignal(str); finished = pyqtSignal(); backendUsed = pyqtSignal(str)
            def __init__(self, output, screen, parent, **kwargs): super().__init__(parent); self.running = False
            def start(self): self.running = True
            def isRunning(self): return self.running
            def finish(self): self.running = False; self.finished.emit()
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}), patch('clipper.app.audio_sources', return_value=[]):
            window = Window(); window.tabs.setCurrentIndex(0); window.backend_combo.setCurrentIndex(0); window.show()
            self.application.processEvents()
            with patch('clipper.app.ScreenPreviewJob', FakeScreenJob):
                for _ in range(3):
                    window.update_screen_preview(); worker = window.screen_preview_worker
                    self.assertIsInstance(worker, FakeScreenJob)
                    worker.finish()
                    self.assertIsNone(window.screen_preview_worker)
                    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                    self.assertTrue(sip.isdeleted(worker))
            window.quitting = True; window.close()

    def test_obs_preview_retries_and_uses_updated_password(self):
        from PyQt6.QtCore import QObject, pyqtSignal
        class FakePreview(QObject):
            frame = pyqtSignal(bytes); error = pyqtSignal(str); finished = pyqtSignal()
            created = []
            def __init__(self, url, password, parent):
                super().__init__(parent); self.password = password; self.running = False; self.interrupted = False
                self.created.append(self)
            def start(self): self.running = True
            def isRunning(self): return self.running
            def requestInterruption(self): self.interrupted = True
            def finish(self): self.running = False; self.finished.emit()
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            window = Window()
            with patch('clipper.obs_preview.PreviewWorker', FakePreview), patch('clipper.app.time.monotonic', return_value=10) as now:
                window.start_obs_inline_preview(); first = FakePreview.created[-1]
                first.error.emit('OBS ještě neběží'); first.finish()
                window.start_obs_inline_preview()
                self.assertEqual(len(FakePreview.created), 1)
                now.return_value = 16
                window.start_obs_inline_preview(); second = FakePreview.created[-1]
                self.assertEqual(len(FakePreview.created), 2)
                window.obs_password.setText('new password')
                self.assertTrue(second.interrupted)
                window.obs_preview.setText('čekám na nové připojení')
                second.error.emit('zastaralá chyba')
                self.assertEqual(window.obs_preview.text(), 'čekám na nové připojení')
                second.finish(); window.start_obs_inline_preview()
                self.assertEqual(FakePreview.created[-1].password, 'new password')
                FakePreview.created[-1].finish()
            window.quitting = True; window.close()

    def test_remastered_workspace_keeps_library_context_menu(self):
        from pathlib import Path
        from PyQt6.QtCore import Qt
        from unittest.mock import patch
        from types import SimpleNamespace
        import clipper.app as app_module
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            clip = Path(d) / 'menu-test.mp4'; clip.touch()
            window = Window(); window.folder = d; window.refresh()
            self.assertEqual([window.tabs.tabText(i).split()[-1] for i in range(window.tabs.count())], ['Nahrávání', 'Knihovna', 'Nastavení'])
            self.assertEqual(window.list.contextMenuPolicy(), Qt.ContextMenuPolicy.CustomContextMenu)
            window.list.item(0).setSelected(True)
            captured = {}
            class Menu:
                def __init__(self, parent): self.items = []; captured['menu'] = self
                def addAction(self, label, handler=None):
                    action = SimpleNamespace(text=lambda: label, setEnabled=lambda enabled: None,
                        triggered=SimpleNamespace(connect=lambda callback: None)); self.items.append(action); return action
                def addMenu(self, label): self.addAction(label); return self
                def addSeparator(self): self.items.append(SimpleNamespace(text=lambda: ''))
                def exec(self, position): captured['executed'] = True
            with patch.object(app_module, 'QMenu', Menu):
                window.context_menu(window.list.viewport().rect().center())
            self.assertTrue(captured.get('executed'))
            self.assertEqual([action.text() for action in captured['menu'].items], [
                'Otevřít umístění souboru', 'Upravit originál', 'Přehrát', 'Uložit střih…',
                'Komprimovaný export…', '', 'Tagy', 'Přidat tag…', 'Odebrat tag…', '',
                'Smazat vybrané soubory…'])
            window.quitting = True; window.close()

    def test_gallery_card_selects_all_group_versions_for_batch_actions(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            original = Path(d) / 'clip.mp4'; original.touch()
            trimmed = Path(d) / 'clip_trim.mp4'; trimmed.touch()
            window = Window(); window.folder = d; window.refresh()
            card = window.list.item(0)
            card.setSelected(True); window.refresh()
            self.assertEqual(window.selected_paths(), [original, trimmed])
            window.quitting = True; window.close()

    def test_batch_delete_versions_preserves_untrimmed_originals(self):
        from pathlib import Path
        from PyQt6.QtWidgets import QMessageBox
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            root = Path(d)
            for name in ('one.mp4', 'one_trim.mp4', 'one_export.mp4', 'two.mp4', 'two_export.mp4'):
                (root / name).touch()
            window = Window(); window.folder = d
            with patch.object(window.thumbnails, 'request', return_value=None), patch.object(QMessageBox, 'question', return_value=QMessageBox.StandardButton.Yes):
                window.refresh(); window.list.selectAll()
                window.delete_selected_versions('original')
                self.assertFalse((root / 'one.mp4').exists())
                self.assertTrue((root / 'one_trim.mp4').exists())
                self.assertTrue((root / 'two.mp4').exists())
                window.list.selectAll(); window.delete_selected_versions('export')
            self.assertFalse((root / 'one_export.mp4').exists())
            self.assertFalse((root / 'two_export.mp4').exists())
            self.assertTrue((root / 'one_trim.mp4').exists())
            self.assertTrue((root / 'two.mp4').exists())
            window.quitting = True; window.close()

    def test_context_menu_toggles_existing_tag_for_multiple_clips(self):
        from pathlib import Path
        from PyQt6.QtCore import QPoint
        from PyQt6.QtWidgets import QMenu
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            one = Path(d) / 'one.mp4'; two = Path(d) / 'two.mp4'; one.touch(); two.touch()
            window = Window(); window.folder = d
            window.library.add_tag('Favorite', '#8246cc'); window.library.tag_clip(one, 'Favorite')
            with patch.object(window.thumbnails, 'request', return_value=None):
                window.refresh(); window.list.selectAll()
                def choose_tag(menu, position):
                    submenu = next(action.menu() for action in menu.actions() if action.text() == 'Tagy')
                    action = next(action for action in submenu.actions() if action.text().startswith('Favorite'))
                    self.assertTrue(action.isCheckable()); self.assertFalse(action.icon().isNull())
                    self.assertIn('část výběru', action.text()); self.assertFalse(action.isChecked())
                    action.trigger()
                with patch.object(QMenu, 'exec', choose_tag): window.context_menu(QPoint(-1, -1))
                self.assertEqual(window.library.tags_for(one), ['Favorite'])
                self.assertEqual(window.library.tags_for(two), ['Favorite'])
                window.list.selectAll()
                def clear_tag(menu, position):
                    submenu = next(action.menu() for action in menu.actions() if action.text() == 'Tagy')
                    action = next(action for action in submenu.actions() if action.text() == 'Favorite')
                    self.assertTrue(action.isChecked()); action.trigger()
                with patch.object(QMenu, 'exec', clear_tag): window.context_menu(QPoint(-1, -1))
            self.assertEqual(window.library.tags_for(one), [])
            self.assertEqual(window.library.tags_for(two), [])
            window.quitting = True; window.close()

    def test_original_is_kept_if_trim_disappears_during_confirmation(self):
        from pathlib import Path
        from PyQt6.QtWidgets import QMessageBox
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            root = Path(d); original = root / 'clip.mp4'; trim = root / 'clip_trim.mp4'
            original.touch(); trim.touch()
            window = Window(); window.folder = d
            with patch.object(window.thumbnails, 'request', return_value=None):
                window.refresh(); window.list.selectAll()
                def remove_trim(*args):
                    trim.unlink(); return QMessageBox.StandardButton.Yes
                with patch.object(QMessageBox, 'question', side_effect=remove_trim):
                    window.delete_selected_versions('original')
            self.assertTrue(original.exists())
            window.quitting = True; window.close()

    def test_linux_backend_preference_selects_matching_page_and_stays_synchronized(self):
        import sys
        if not sys.platform.startswith('linux'): self.skipTest('Linux-only recording backend selector')
        from PyQt6.QtWidgets import QStackedWidget
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            first = Window(); first.library.set_setting('linux_backend', '1')
            first.quitting = True; first.close()
            window = Window()
            capture_pages = next(stack for stack in window.findChildren(QStackedWidget) if stack.count() == 2)
            self.assertEqual(window.backend_combo.currentIndex(), 1)
            self.assertEqual(window.shortcut_backend.currentIndex(), 1)
            self.assertEqual(capture_pages.currentIndex(), 1)
            window.backend_combo.setCurrentIndex(0)
            self.assertEqual(window.shortcut_backend.currentIndex(), 0)
            self.assertEqual(capture_pages.currentIndex(), 0)
            window.quitting = True; window.close()

    def test_recording_events_store_their_own_audio_metadata(self):
        from pathlib import Path
        from clipper.recorder import SavedReplay
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            window = Window()
            first, second = Path(d) / 'first.mkv', Path(d) / 'second.mkv'
            first.touch(); second.touch()
            window.folder = d
            window.recorder.first_is_mix = False
            window.recorder.saved.put(SavedReplay(str(first), True, ('Mix', 'Game', 'Mic')))
            window.recorder.saved.put(SavedReplay(str(second), False, ('Mic',)))
            window.check_native_recorder()
            self.assertEqual(window.library.edit_for(first), {'mix_first': True, 'track_names': ['Mix', 'Game', 'Mic']})
            self.assertEqual(window.library.edit_for(second), {'mix_first': False, 'track_names': ['Mic']})
            window.quitting = True; window.close()

    def test_copy_export_from_group_excludes_original_and_trim(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            for name in ('clip.mp4', 'clip_trim.mp4', 'clip_export.mp4'):
                (Path(d) / name).touch()
            window = Window(); window.folder = d; window.refresh()
            group = window.list.item(0); group.setSelected(True)
            window.copy_exports()
            urls = QApplication.clipboard().mimeData().urls()
            self.assertEqual([Path(url.toLocalFile()) for url in urls], [Path(d) / 'clip_export.mp4'])
            window.quitting = True; window.close()

    def test_play_uses_multitrack_editor_and_starts_playback(self):
        from pathlib import Path
        from PyQt6.QtCore import QEventLoop, QTimer, Qt
        from PyQt6.QtWidgets import QDialog
        events = []
        class FakeEditor(QDialog):
            def __init__(self, path, parent, info, preview_mode=False):
                super().__init__(parent); self.path = path; self.operation = None; self.proxy = None; self.preview_mode = preview_mode; events.append(('open', path))
            def request_autoplay(self): events.append(('play',))
            def result_values(self): return (0, 1, {}, False)
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            clip = Path(d) / 'clip.mkv'; clip.touch(); window = Window()
            with patch.object(window, 'probe_selected', side_effect=lambda callback: callback(clip, {})), patch('clipper.editor.Editor', FakeEditor):
                window.play()
            self.assertEqual(events[0], ('open', clip))
            self.assertIsNotNone(window.active_editor)
            self.assertTrue(window.tabs.isHidden())
            loop = QEventLoop(); QTimer.singleShot(30, loop.quit); loop.exec()
            self.assertEqual(events, [('open', clip), ('play',)])
            window.active_editor.finished.emit(QDialog.DialogCode.Rejected)
            self.assertIsNone(window.active_editor)
            self.assertFalse(window.tabs.isHidden())
            window.quitting = True; window.close()

    def test_capture_can_run_while_export_is_busy(self):
        import threading
        from PyQt6.QtCore import QEventLoop, QTimer
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            window = Window(); release = threading.Event(); started = threading.Event()
            window.start_job(lambda: release.wait(5))
            window.start_job(lambda: (started.set() or 'saved'), capture=True)
            loop = QEventLoop()
            QTimer.singleShot(300, loop.quit); loop.exec()
            self.assertTrue(started.is_set())
            release.set()
            loop = QEventLoop(); QTimer.singleShot(300, loop.quit); loop.exec()
            window.quitting = True; window.close()

    def test_new_version_inherits_group_tags(self):
        from pathlib import Path
        from PyQt6.QtCore import QEventLoop, QTimer
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            source=Path(d)/'clip.mp4'; source.touch(); dest=Path(d)/'clip_trim.mp4'
            window=Window(); window.library.add_tag('funny'); window.library.tag_clip(source, 'funny')
            window.start_media_job(lambda progress, cancel: dest.write_bytes(b'data'), source, dest)
            loop=QEventLoop(); QTimer.singleShot(500, loop.quit); loop.exec()
            self.assertEqual(window.library.tags_for(dest), ['funny'])
            window.quitting=True; window.close()

    def test_version_picker_keeps_current_version_across_library_refresh(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            original = Path(d) / 'clip.mp4'; original.touch()
            trimmed = Path(d) / 'clip_trim.mp4'; trimmed.touch()
            window = Window(); window.folder = d; window.refresh()
            card = window.list.item(0); window.list.setCurrentItem(card); card.setSelected(True)
            window.detail_version.setCurrentIndex(window.detail_version.findData(str(trimmed)))
            window.refresh()
            self.assertEqual(window.selected(), trimmed)
            window.search.setText('trim')
            self.assertEqual(window.list.count(), 1)
            self.assertEqual(window.selected(), trimmed)
            window.list.clearSelection()
            self.assertIsNone(window.selected())
            window.quitting = True; window.close()

    def test_custom_export_name_remains_with_original_after_restart(self):
        from pathlib import Path
        from PyQt6.QtCore import QEventLoop, QTimer
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            original = Path(d) / 'game.mp4'; original.touch()
            output = Path(d) / 'my favorite moment.mp4'
            window = Window(); window.folder = d
            window.start_media_job(lambda progress, cancel: output.write_bytes(b'data'), original, output, kind='export')
            loop = QEventLoop(); QTimer.singleShot(500, loop.quit); loop.exec()
            window.refresh()
            self.assertEqual(window.list.count(), 1)
            self.assertEqual(window.list.item(0).data(0x0100 + 2)['export'], [str(output)])
            window.quitting = True; window.close()
            window = Window(); window.folder = d; window.refresh()
            self.assertEqual(window.list.count(), 1)
            versions = window.list.item(0).data(0x0100 + 2)
            self.assertEqual(sum(map(len, versions.values())), 2)
            window.quitting = True; window.close()

    def test_obs_own_replay_remembers_legacy_mix(self):
        from pathlib import Path
        from PyQt6.QtCore import QEventLoop, QTimer
        from clipper.obs_setup import PROFILE, COLLECTION
        class FakeOBS:
            def __init__(self, *args): pass
            def save(self): return str(clip)
            def request(self, name):
                if name == 'GetProfileList': return {'currentProfileName': PROFILE}
                if name == 'GetSceneCollectionList': return {'currentSceneCollectionName': COLLECTION}
                return {}
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            clip = Path(d) / 'replay.mkv'; clip.touch()
            window = Window()
            with patch('clipper.app.OBSClient', FakeOBS), patch('clipper.app.active_window_name', return_value='Game'):
                window.obs_action('save')
                loop = QEventLoop(); QTimer.singleShot(500, loop.quit); loop.exec()
            self.assertTrue(window.library.edit_for(clip)['mix_first'])
            window.quitting = True; window.close()

    def test_obs_next_save_is_not_blocked_by_optional_metadata(self):
        import threading
        from pathlib import Path
        from PyQt6.QtCore import QEventLoop, QTimer
        from clipper.obs_setup import PROFILE, COLLECTION
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            paths = [Path(d) / 'one.mkv', Path(d) / 'two.mkv']
            for path in paths: path.touch()
            release = threading.Event(); saves = []
            class FakeOBS:
                def __init__(self, *args, **kwargs): pass
                def save(self):
                    path = paths[len(saves)]; saves.append(path); return str(path)
                def request(self, operation):
                    release.wait(3)
                    return {'currentProfileName': PROFILE} if operation == 'GetProfileList' else {'currentSceneCollectionName': COLLECTION}
            window = Window(); window.folder = d
            with patch('clipper.app.OBSClient', FakeOBS), patch('clipper.app.active_window_name', return_value='Game'):
                window.obs_action('save')
                loop = QEventLoop()
                QTimer.singleShot(200, lambda: window.obs_action('save'))
                QTimer.singleShot(400, release.set)
                QTimer.singleShot(1100, loop.quit)
                loop.exec()
                self.assertEqual(saves, paths)
                renamed = [path.with_name('Game_' + path.name) for path in paths]
                self.assertTrue(all(path.exists() and window.library.edit_for(path).get('mix_first') for path in renamed))
            window.quitting = True; window.close()

    def test_rejected_obs_command_keeps_status_and_monitor_generation(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            window = Window()
            window.obs_state_label.setText('Replay buffer běží')
            generation = window.obs_generation
            with patch.object(window, 'start_job', return_value=False), patch.object(window, 'save_obs_secret', return_value=True):
                window.obs_action('stop')
            self.assertEqual(window.obs_state_label.text(), 'Replay buffer běží')
            self.assertEqual(window.obs_generation, generation)
            window.quitting = True; window.close()

    def test_slow_window_lookup_does_not_delay_next_confirmed_obs_save(self):
        import threading
        from pathlib import Path
        from PyQt6.QtCore import QEventLoop, QTimer
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            paths = [Path(d) / 'first.mkv', Path(d) / 'second.mkv']
            for path in paths: path.write_bytes(b'clip')
            release = threading.Event(); saves = []
            class FakeOBS:
                def __init__(self, *args): pass
                def save(self):
                    path = paths[len(saves)]; saves.append(path); return str(path)
                def request(self, name): return {}
            def slow_title():
                release.wait(3); return 'Game'
            window = Window(); window.folder = d
            try:
                with patch('clipper.app.OBSClient', FakeOBS), patch('clipper.app.active_window_name', side_effect=slow_title), patch.object(window, 'refresh'):
                    window.obs_action('save')
                    loop = QEventLoop()
                    QTimer.singleShot(200, lambda: window.obs_action('save'))
                    QTimer.singleShot(400, loop.quit); loop.exec()
                    self.assertEqual(saves, paths)
                    release.set()
                    loop = QEventLoop(); QTimer.singleShot(400, loop.quit); loop.exec()
                    self.assertTrue(all(path.with_name('Game_' + path.name).exists() for path in paths))
            finally:
                release.set(); window.quitting = True; window.close()

    def test_finalizing_obs_clip_is_hidden_until_named_and_audio_metadata_saved(self):
        import threading
        from pathlib import Path
        from PyQt6.QtCore import QEventLoop, QTimer
        from clipper.obs_setup import PROFILE, COLLECTION
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            clip = Path(d) / 'Replay_1.mkv'; clip.touch(); release = threading.Event()
            class FakeOBS:
                def __init__(self, *args): pass
                def save(self): return str(clip)
                def request(self, operation):
                    release.wait(3)
                    return {'currentProfileName': PROFILE} if operation == 'GetProfileList' else {'currentSceneCollectionName': COLLECTION}
            window = Window(); window.folder = d
            try:
                with patch('clipper.app.OBSClient', FakeOBS), patch('clipper.app.active_window_name', return_value='Game'), patch.object(window.thumbnails, 'request', return_value=None):
                    window.obs_action('save')
                    loop = QEventLoop(); QTimer.singleShot(250, loop.quit); loop.exec()
                    window.refresh(); self.assertEqual(window.list.count(), 0)
                    release.set()
                    loop = QEventLoop(); QTimer.singleShot(500, loop.quit); loop.exec()
                    renamed = Path(d) / 'Game_1.mkv'
                    self.assertTrue(renamed.exists())
                    self.assertTrue(window.library.edit_for(renamed)['mix_first'])
                    self.assertEqual(window.list.count(), 1)
            finally:
                release.set(); window.quitting = True; window.close()

    def test_failed_hotkey_change_restores_previous_bindings(self):
        from PyQt6.QtCore import QObject, QTimer, QEventLoop, pyqtSignal
        from PyQt6.QtWidgets import QLineEdit
        class Hotkeys(QObject):
            activated = pyqtSignal(str); error = pyqtSignal(str); registered = pyqtSignal(); finished = pyqtSignal()
            def __init__(self, bindings, parent): super().__init__(parent); self.bindings = bindings
            def start(self):
                def complete():
                    if self.bindings['save'] == 'F11':
                        self.error.emit('Zkratku používá jiný program'); self.finished.emit()
                    else: self.registered.emit()
                QTimer.singleShot(0, complete)
            def requestInterruption(self): pass
            def wait(self): return True
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            window = Window(); window.save_key = QLineEdit('F11'); window.toggle_key = QLineEdit('F9')
            with patch('clipper.app.WindowsHotkeys', Hotkeys):
                window.apply_hotkeys()
                loop = QEventLoop(); QTimer.singleShot(100, loop.quit); loop.exec()
                self.assertEqual(window.save_key.text(), 'F10')
                self.assertEqual(window.library.setting('save_key'), 'F10')
                self.assertEqual(window.hotkeys.bindings['save'], 'F10')
            window.quitting = True; window.close()

    def test_stopped_hotkey_registration_cannot_update_window(self):
        from PyQt6.QtCore import QObject, pyqtSignal
        class Hotkeys(QObject):
            activated = pyqtSignal(str); error = pyqtSignal(str); registered = pyqtSignal(); finished = pyqtSignal()
            def __init__(self, bindings, parent): super().__init__(parent); self.interrupted = False
            def start(self): pass
            def requestInterruption(self): self.interrupted = True
            def wait(self): return True
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            with patch('clipper.app.WindowsHotkeys', Hotkeys):
                window = Window(); window.stop_hotkeys()
                window._register_hotkeys({'save':'F10', 'toggle':'F9'})
                worker = window.hotkeys; before = window.status.text()
                window.stop_hotkeys()
                worker.error.emit('stará chyba'); worker.registered.emit(); worker.finished.emit()
                self.assertTrue(worker.interrupted)
                self.assertIsNone(window.hotkeys)
                self.assertEqual(window.status.text(), before)
            window.quitting = True; window.close()

    def test_copy_export_uses_newest_or_explicitly_selected_version(self):
        from pathlib import Path
        from PyQt6.QtCore import Qt
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            original = Path(d)/'clip.mp4'; newer = Path(d)/'clip_export.mp4'; older = Path(d)/'older_export.mp4'
            for path in (original, older, newer): path.touch()
            os.utime(older, (100, 100)); os.utime(newer, (200, 200))
            window = Window(); window.library.set_version(older, 'clip', 'export'); window.folder = d; window.refresh(); item = window.list.item(0)
            item.setSelected(True); window.list.setCurrentItem(item)
            self.assertEqual(window.selected_export_paths(), [newer])
            index = window.detail_version.findData(str(older)); window.detail_version.setCurrentIndex(index)
            self.assertEqual(window.selected_export_paths(), [older])
            window.quitting = True; window.close()

    def test_unexpected_gsr_exit_restores_recording_controls(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            window = Window(); window.set_gsr_ui_state(True); window.recorder.expect_running = True; window.recorder.process = None
            window.check_native_recorder()
            self.assertTrue(window.gsr_start_button.isEnabled())
            self.assertFalse(window.gsr_save_button.isEnabled())
            self.assertFalse(window.gsr_stop_button.isEnabled())
            self.assertIn('neočekávaně', window.gsr_state_label.text())
            window.quitting = True; window.close()

    def test_scale_is_committed_only_by_restart(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            window = Window(); initial = window.library.setting('ui_scale', '1')
            window.ui_scale.setValue(150)
            self.assertEqual(window.library.setting('ui_scale', '1'), initial)
            self.assertTrue(window.scale_restart.isEnabled())
            window.quitting = True; window.close()

    def test_queued_obs_save_continues_after_current_operation(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            window = Window(); running = Mock(); running.isRunning.return_value = True; window.capture_thread = running
            self.assertTrue(window.obs_action('save'))
            self.assertEqual(window.obs_pending_saves, 1)
            window.capture_thread = None
            with patch.object(window, 'obs_action') as following:
                window.continue_obs_saves(); self.application.processEvents()
                following.assert_called_once_with('save')
            self.assertEqual(window.obs_pending_saves, 0)
            if window.thread:
                from PyQt6.QtCore import QEventLoop, QTimer
                loop = QEventLoop(); window.thread.finished.connect(loop.quit); QTimer.singleShot(7000, loop.quit); loop.exec()
            window.quitting = True; window.close()

    def test_restart_launches_after_close_is_accepted(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            window = Window(); window._restart_pending = True; window.quitting = True
            with patch.object(window, 'launch_replacement') as launch:
                window.close(); self.application.processEvents()
                launch.assert_called_once_with()

    def test_remember_password_is_saved_when_checkbox_changes(self):
        from PyQt6.QtWidgets import QLineEdit, QCheckBox
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            window = Window(); window.obs_password = QLineEdit('secret'); window.remember_secret = QCheckBox()
            window.remember_secret.setChecked(True)
            with patch('clipper.app.protect', return_value='encrypted'):
                self.assertTrue(window.save_obs_secret())
            self.assertEqual(window.library.setting('obs_secret'), 'encrypted')
            window.remember_secret.setChecked(False); window.save_obs_secret()
            self.assertEqual(window.library.setting('obs_secret'), '')
            window.quitting = True; window.close()

    def test_cancel_media_job_stops_without_registering_version(self):
        import time
        from pathlib import Path
        from PyQt6.QtCore import QEventLoop, QTimer
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            source = Path(d) / 'clip.mp4'; source.touch(); dest = Path(d) / 'clip_export.mp4'
            window = Window()
            def action(progress, cancel):
                while True:
                    cancel.check(); time.sleep(.01)
            window.start_media_job(action, source, dest, kind='export')
            self.assertTrue(window.cancel_button.isEnabled())
            loop = QEventLoop()
            QTimer.singleShot(50, window.cancel_media); QTimer.singleShot(350, loop.quit); loop.exec()
            self.assertFalse(window.cancel_button.isEnabled())
            self.assertIn('zrušeno', window.status.text())
            self.assertFalse(window.library.versions())
            window.quitting = True; window.close()

    def test_obs_health_warns_after_repeated_failure_and_recovers(self):
        from PyQt6.QtCore import QEventLoop, QTimer
        class FakeOBS:
            available = False
            def __init__(self, *args, **kwargs): pass
            def status(self): return self.available
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            window = Window(); window.set_obs_expected(True, ('ws://127.0.0.1:4455', ''))
            def poll():
                window.check_obs_health(); loop = QEventLoop(); QTimer.singleShot(150, loop.quit); loop.exec()
            with patch('clipper.app.OBSClient', FakeOBS):
                poll(); self.assertFalse(window.obs_warned)
                poll(); self.assertTrue(window.obs_warned); self.assertIn('neběží', window.status.text())
                FakeOBS.available = True; poll()
                self.assertFalse(window.obs_warned); self.assertIn('znovu aktivní', window.status.text())
            window.quitting = True; window.close()

    def test_stale_obs_health_result_does_not_report_after_stop(self):
        import time
        from PyQt6.QtCore import QEventLoop, QTimer
        class FakeOBS:
            def __init__(self, *args, **kwargs): pass
            def status(self): time.sleep(.15); return False
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            window = Window(); window.set_obs_expected(True, ('ws://127.0.0.1:4455', '')); window.obs_failures = 1
            with patch('clipper.app.OBSClient', FakeOBS):
                window.check_obs_health(); window.set_obs_expected(False, ('ws://127.0.0.1:4455', ''))
                loop = QEventLoop(); QTimer.singleShot(400, loop.quit); loop.exec()
            self.assertFalse(window.obs_warned)
            self.assertFalse(window.obs_health_timer.isActive())
            window.quitting = True; window.close()

    def test_close_waits_for_active_obs_health_check(self):
        import time
        from PyQt6.QtCore import QEventLoop, QTimer
        class FakeOBS:
            def __init__(self, *args, **kwargs): pass
            def status(self): time.sleep(.2); return True
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            window = Window(); window.set_obs_expected(True, ('ws://127.0.0.1:4455', ''))
            with patch('clipper.app.OBSClient', FakeOBS):
                window.check_obs_health(); window.quitting = True; window.close()
                self.assertTrue(window.closing_after_health)
                loop = QEventLoop(); QTimer.singleShot(500, loop.quit); loop.exec()
            self.assertIsNone(window.obs_health_thread)
            with self.assertRaises(Exception): window.library.setting('folder')

    def test_successful_obs_start_and_stop_control_monitoring(self):
        from PyQt6.QtCore import QEventLoop, QTimer
        class FakeOBS:
            def __init__(self, *args, **kwargs): pass
            def start(self): pass
            def stop(self): pass
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            window = Window()
            def wait():
                loop = QEventLoop(); QTimer.singleShot(200, loop.quit); loop.exec()
            with patch('clipper.app.OBSClient', FakeOBS):
                window.obs_action('start'); wait()
                self.assertTrue(window.obs_expected); self.assertTrue(window.obs_health_timer.isActive())
                window.obs_action('stop'); wait()
                self.assertFalse(window.obs_expected); self.assertFalse(window.obs_health_timer.isActive())
            window.quitting = True; window.close()

    def test_gallery_card_shows_saved_tag_colors_and_has_thumbnail_canvas(self):
        from pathlib import Path
        from PyQt6.QtCore import Qt
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            clip = Path(d) / 'clip.mp4'; clip.touch()
            window = Window(); window.folder = d
            window.library.add_tag('Favorite', '#8246cc'); window.library.tag_clip(clip, 'Favorite')
            window.refresh(); item = window.list.item(0)
            self.assertIsNotNone(item)
            self.assertEqual(item.data(Qt.ItemDataRole.UserRole + 1), [('Favorite', '#8246cc')])
            self.assertGreater(window.list.itemDelegate().sizeHint(None, window.list.model().index(0, 0)).height(), 180)
            window.quitting = True; window.close()

    def test_quick_trim_rebuilds_mix_and_saves_new_version_metadata(self):
        import array
        import subprocess
        from pathlib import Path
        from PyQt6.QtCore import QEventLoop, QTimer
        from clipper.media import run, probe
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            source = Path(d) / 'clip.mkv'; destination = Path(d) / 'clip_trim.mp4'
            run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=10',
                 '-f', 'lavfi', '-i', 'sine=frequency=440', '-f', 'lavfi', '-i', 'sine=frequency=440',
                 '-f', 'lavfi', '-i', 'sine=frequency=880', '-t', '2', '-map', '0:v', '-map', '1:a',
                 '-map', '2:a', '-map', '3:a', '-c:v', 'libx264', '-c:a', 'aac', str(source)])
            indices = [stream['index'] for stream in probe(source)['streams'] if stream['codec_type'] == 'audio']
            levels = {indices[0]: 1, indices[1]: 0, indices[2]: 0}
            window = Window(); window.library.save_edit(source, {'track_names': ['Mix', 'Hra', 'Discord']})
            window.library.save_edit(destination, {'in': .8, 'out': .9, 'mix_first': False})
            with patch.object(window, 'selection', return_value=(source, str(destination), 0, 1.5, 10, levels, True)):
                window.quick_operation(False, source, probe(source))
                loop = QEventLoop(); window.thread.finished.connect(loop.quit); QTimer.singleShot(15000, loop.quit); loop.exec()
            self.assertTrue(destination.exists())
            self.assertEqual(window.library.edit_for(destination), {'mix_first': True, 'track_names': ['Mix', 'Hra', 'Discord']})
            raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(destination), '-map', '0:a:0',
                                  '-f', 's16le', '-acodec', 'pcm_s16le', '-'], capture_output=True, check=True).stdout
            samples = array.array('h'); samples.frombytes(raw)
            self.assertLess(max(abs(value) for value in samples), 10)
            window.quitting = True; window.close()

    def test_quick_operation_restores_saved_range_and_track_levels(self):
        from pathlib import Path
        from PyQt6.QtWidgets import QDialog, QDoubleSpinBox
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            source = Path(d) / 'source.mp4'; source.touch(); window = Window()
            window.library.save_edit(source, {'in': .2, 'out': .7, 'volumes': {'1': .5, '2': 2}, 'mix_first': True})
            seen = []
            def inspect(dialog):
                seen.extend(spin.value() for spin in dialog.findChildren(QDoubleSpinBox))
                return QDialog.DialogCode.Rejected
            info = {'format': {'duration': '10'}, 'streams': [{'codec_type': 'audio', 'index': 1}, {'codec_type': 'audio', 'index': 2}]}
            with patch.object(window, 'selected', return_value=source), patch('clipper.app.probe', return_value=info), patch.object(QDialog, 'exec', inspect):
                self.assertIsNone(window.selection(False))
            self.assertEqual(seen, [2, 7, .5, 2])
            window.quitting = True; window.close()

    def test_quick_trim_exposes_mix_option(self):
        from pathlib import Path
        from PyQt6.QtWidgets import QCheckBox, QDialog
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            source = Path(d) / 'source.mp4'; source.touch()
            window = Window(); window.library.save_edit(source, {'mix_first': True}); seen = []
            def inspect(dialog):
                boxes = dialog.findChildren(QCheckBox)
                seen.extend((box.text(), box.isChecked()) for box in boxes)
                return QDialog.DialogCode.Rejected
            info = {'format': {'duration': '5'}, 'streams': [{'codec_type': 'audio', 'index': 1}, {'codec_type': 'audio', 'index': 2}]}
            with patch.object(window, 'selected', return_value=source), patch('clipper.app.probe', return_value=info), patch.object(QDialog, 'exec', inspect):
                self.assertIsNone(window.selection(False))
            self.assertIn(('První stopa je mix ostatních stop', True), seen)
            window.quitting = True; window.close()

    def test_obs_setup_persists_additional_track_configuration(self):
        import json
        from PyQt6.QtWidgets import QDialog
        from clipper.audio_sources_ui import ExtraAudioEditor
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            window = Window(); window.folder = d
            def accept(dialog):
                editor = dialog.findChild(ExtraAudioEditor)
                enabled, title, kind, device, gain = editor.rows[0]
                enabled.setChecked(True); title.setText('Discord'); gain.setValue(70)
                device.addItem('Chat output', 'chat-device'); device.setCurrentIndex(device.findData('chat-device'))
                return QDialog.DialogCode.Accepted
            def execute(action, capture=False, on_done=None, **kwargs):
                message = action()
                if on_done: on_done(message)
                return True
            with patch.object(QDialog, 'exec', accept), patch.object(window, 'start_job', side_effect=execute), patch('clipper.app.OBSClient'), patch('clipper.app.configure_windows') as configure:
                window.configure_obs()
            settings = configure.call_args.args[1]
            self.assertEqual(settings.extra_audio[0].name, 'Discord')
            self.assertEqual(settings.extra_audio[0].device, 'chat-device')
            self.assertAlmostEqual(settings.extra_audio[0].gain, .7)
            self.assertEqual(json.loads(window.library.setting('obs_active_track_names'))[-1], 'Discord')
            window.quitting = True; window.close()

    def test_slow_probe_keeps_ui_responsive_and_returns_selected_file(self):
        import time
        from pathlib import Path
        from PyQt6.QtCore import QEventLoop, QTimer
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            source = Path(d) / 'clip.mp4'; source.touch(); window = Window()
            events = []
            def slow_probe(path):
                time.sleep(.35); return {'format': {'duration':'2'}, 'streams': []}
            with patch.object(window, 'selected', return_value=source), patch('clipper.app.probe', side_effect=slow_probe):
                window.probe_selected(lambda path, info: events.append(('result', path, info['format']['duration'])))
                loop = QEventLoop(); QTimer.singleShot(50, lambda: events.append(('timer',)))
                QTimer.singleShot(700, loop.quit); loop.exec()
            self.assertEqual(events[0], ('timer',))
            self.assertEqual(events[1], ('result', source, '2'))
            window.quitting = True; window.close()

    def test_job_callback_can_start_next_job_immediately(self):
        from PyQt6.QtCore import QEventLoop, QTimer
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            window = Window(); completed = []
            window.start_job(lambda: 'first', on_done=lambda _: window.start_job(lambda: 'second', on_done=completed.append))
            loop = QEventLoop(); QTimer.singleShot(500, loop.quit); loop.exec()
            self.assertEqual(completed, ['second'])
            window.quitting = True; window.close()

    def test_quick_trim_continues_after_background_probe(self):
        from pathlib import Path
        from PyQt6.QtCore import QEventLoop, QTimer
        from PyQt6.QtWidgets import QDialog, QFileDialog
        from clipper.media import run
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {'APPDATA': d, 'XDG_DATA_HOME': d}):
            source = Path(d) / 'clip.mp4'; destination = Path(d) / 'clip_trim.mp4'
            run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=80x60:rate=10',
                 '-t', '2', '-c:v', 'libx264', str(source)])
            window = Window()
            with patch.object(window, 'selected', return_value=source), patch.object(QDialog, 'exec', return_value=QDialog.DialogCode.Accepted), patch.object(QFileDialog, 'getSaveFileName', return_value=(str(destination), '')):
                window.make_trim()
                loop = QEventLoop(); timer = QTimer(); timer.setInterval(50)
                timer.timeout.connect(lambda: loop.quit() if destination.exists() and window.thread is None else None)
                timer.start(); QTimer.singleShot(10000, loop.quit); loop.exec(); timer.stop()
            self.assertTrue(destination.exists())
            self.assertIsNone(window.thread)
            window.quitting = True; window.close()
