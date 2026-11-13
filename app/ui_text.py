"""Interface texts in English, German and Russian: the live window, the console questions, the
names of the shortcuts and menu entries.

The language is, in this order: --ui-language (which is also remembered), the one chosen last
in the window or with --ui-language (app/ui.local.ini, [ui] language), the language of the
shortcuts already in the tool folder (an installation from before 2026-11-13 stays Russian
although the system may be English), the system's display language if it is one of these, else
English.

Only what people read is translated. Progress messages and errors are in English for everyone;
the transcript itself, its speaker labels ("Вы", "Speaker 2") and the summary follow the
language of the meeting, not this one.
"""
import configparser
import os

LANGUAGES = {"en": "English", "de": "Deutsch", "ru": "Русский"}
DEFAULT = "en"
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui.local.ini")

_current = None

# key -> (English, German, Russian). {name} placeholders are filled by t(key, name=...).
TEXTS = {
    # --- shared -------------------------------------------------------------------------------
    "yes": ("yes", "ja", "да"),
    "no": ("no", "nein", "нет"),
    "your_choice": ("Your choice: ", "Ihre Wahl: ", "Ваш выбор: "),
    "not_understood": ("  Not understood. Type a number from the list or just press Enter.",
                       "  Nicht verstanden. Geben Sie eine Nummer aus der Liste ein oder drücken Sie einfach Enter.",
                       "  Не понял ответ, введите номер из списка или просто нажмите Enter."),
    "meeting.auto": ("Detect automatically", "Automatisch erkennen", "Определить автоматически"),
    "meeting.en": ("English", "Englisch", "Английский"),
    "meeting.de": ("German", "Deutsch", "Немецкий"),
    "meeting.ru": ("Russian", "Russisch", "Русский"),
    "meeting.fr": ("French", "Französisch", "Французский"),
    "meeting.multi": ("Several languages", "Mehrere Sprachen", "Несколько языков"),

    # --- console questions (drop-files-here, --ask) ---------------------------------------------
    "drop_files": ("Drag the recording (or several) into this window and press Enter:",
                   "Ziehen Sie die Aufnahme (oder mehrere) in dieses Fenster und drücken Sie Enter:",
                   "Перетащите файл записи (или несколько) в это окно и нажмите Enter:"),
    "ask.language": ("Language of the recording:", "Sprache der Aufnahme:", "Язык записи:"),
    "ask.detect": ("don't know, detect automatically", "weiß nicht, automatisch erkennen",
                   "не знаю, определить автоматически"),
    "ask.split": ("Split the text by speaker (by voice)? This adds a few minutes.",
                  "Text nach Sprechern (nach Stimme) trennen? Das dauert ein paar Minuten länger.",
                  "Разделить текст по говорящим (по голосам)? Это добавит несколько минут."),
    "ask.count": ("How many people speak in the recording?", "Wie viele Personen sprechen in der Aufnahme?",
                  "Сколько человек говорит на записи?"),
    "ask.count_option": ("1-20 - number of speakers", "1-20 - Anzahl der Sprecher", "1-20 - число говорящих"),
    "ask.check": (
        "Check the text with an AI? It puts in names instead of \"Speaker N\" where people\n"
        "introduced themselves or were addressed by name, and repairs phrases split between\n"
        "speakers. The original text is kept; the checked one goes to <name>.checked.txt.",
        "Text mit einer KI prüfen? Sie setzt Namen statt „Sprecher N“ ein, wo sich Personen\n"
        "vorgestellt haben oder mit Namen angesprochen wurden, und repariert Sätze, die zwischen\n"
        "Sprechern zerrissen sind. Der Originaltext bleibt, der geprüfte steht in <Name>.checked.txt.",
        "Проверить текст с помощью ИИ? ИИ подставит имена вместо «Говорящий N», где люди\n"
        "представились или к ним обратились по имени, и исправит разорванные между\n"
        "говорящими фразы. Исходный текст сохранится, исправленный будет в <имя>.checked.txt."),
    "ask.summary": ("Make a summary with an AI?", "Eine Zusammenfassung mit einer KI erstellen?",
                    "Сделать выжимку с помощью ИИ?"),
    "ask.translate": ("Translate the text into another language? Locally, nothing leaves the computer.",
                      "Den Text in eine andere Sprache übersetzen? Lokal, nichts verlässt den Computer.",
                      "Перевести текст на другой язык? Локально, текст никуда не уходит."),
    "ask.check_translation": ("Check the translation with an AI? It corrects clear mistakes of meaning,\n"
                              "numbers and names; the machine translation is kept next to it.",
                              "Die Übersetzung mit einer KI prüfen? Sie korrigiert klare Fehler bei Sinn,\n"
                              "Zahlen und Namen; die maschinelle Übersetzung bleibt daneben erhalten.",
                              "Проверить перевод с помощью ИИ? Он исправит явные ошибки в смысле, числах\n"
                              "и именах; машинный перевод сохранится рядом."),
    "ask.ai_rules": (
        "\nFor the check and the summary the transcript goes to the chosen AI under your account\n"
        "(a local model keeps it on the computer), so only if the rules you work under allow it.",
        "\nFür die Prüfung und die Zusammenfassung geht der Text an die gewählte KI unter Ihrem Konto\n"
        "(ein lokales Modell behält ihn auf dem Computer), also nur, wenn Ihre Regeln das erlauben.",
        "\nДля проверки и выжимки текст расшифровки уйдёт в выбранный ИИ под вашим аккаунтом\n"
        "(у локальной модели останется на компьютере), поэтому только если ваши правила это разрешают."),

    # --- finding the AI -------------------------------------------------------------------------
    "ai.searching_console": (
        "\nLooking for installed AIs (Claude Code, Codex (ChatGPT), local models in Ollama and "
        "LM Studio) and checking the login...",
        "\nSuche installierte KIs (Claude Code, Codex (ChatGPT), lokale Modelle in Ollama und "
        "LM Studio) und prüfe die Anmeldung...",
        "\nИщу установленные ИИ (Claude Code, Codex (ChatGPT), локальные модели Ollama и "
        "LM Studio) и проверяю, выполнен ли в них вход..."),
    "ai.installed_but": ("{title}: installed, but {reason}", "{title}: installiert, aber {reason}",
                         "{title}: установлен, но {reason}"),
    "ai.nothing": ("nothing", "nichts", "ничего"),
    "ai.ready": ("Ready ({seconds} s): {names}.", "Bereit ({seconds} s): {names}.",
                 "Готово к работе ({seconds} с): {names}."),
    "ai.which": ("Which AI should be used?", "Welche KI soll verwendet werden?", "Какой ИИ использовать?"),
    "ai.none_found": ("\nNo Claude Code, no Codex (ChatGPT) and no local model (Ollama, LM Studio) found.",
                      "\nWeder Claude Code noch Codex (ChatGPT) noch ein lokales Modell (Ollama, LM Studio) gefunden.",
                      "\nНе найден ни Claude Code, ни Codex (ChatGPT), ни локальная модель (Ollama, LM Studio)."),
    "ai.what_now": ("What now?", "Was nun?", "Что сделать?"),
    "ai.option_skip": ("1 - skip the check and the summary (the text is made anyway)",
                       "1 - Prüfung und Zusammenfassung auslassen (der Text entsteht trotzdem)",
                       "1 - отменить проверку и выжимку (текст всё равно будет)"),
    "ai.option_path": ("2 - enter the path to an installed AI", "2 - Pfad zu einer installierten KI angeben",
                       "2 - указать путь к установленному ИИ"),
    "ai.skip": ("skip", "auslassen", "отменить"),
    "ai.path_prompt": ("Path to claude or codex (or its folder), or the address of a local server,\n"
                       "for example http://127.0.0.1:11434:",
                       "Pfad zu claude oder codex (oder dessen Ordner) oder die Adresse eines lokalen Servers,\n"
                       "zum Beispiel http://127.0.0.1:11434:",
                       "Путь к claude или codex (можно папку с ним), или адрес локального сервера,\n"
                       "например http://127.0.0.1:11434:"),
    "ai.found_but": ("  Found, but {reason}.", "  Gefunden, aber {reason}.", "  Найден, но {reason}."),
    "ai.found_saved": ("Found: {name}. The path is remembered for next time.",
                       "Gefunden: {name}. Der Pfad wird für die nächsten Male gespeichert.",
                       "Найдено: {name}. Путь запомнен для следующих запусков."),
    "ai.path_wrong": ("  Neither claude nor codex at this path, and no local server answers there.",
                      "  Unter diesem Pfad gibt es weder claude noch codex, und kein lokaler Server antwortet.",
                      "  По этому пути не нашёлся ни claude, ни codex, и локальный сервер не отвечает."),
    "ai.local": ("local model", "lokales Modell", "локальная модель"),
    "login.server": ("the server does not answer", "der Server antwortet nicht", "сервер не отвечает"),
    "login.old_claude": ("login not checked (old version of Claude Code)",
                         "Anmeldung nicht geprüft (alte Version von Claude Code)",
                         "вход не проверен (старая версия Claude Code)"),
    "login.claude": ("not logged in: start claude and log in (/login)",
                     "nicht angemeldet: claude starten und anmelden (/login)",
                     "вход не выполнен: запустите claude и войдите (/login)"),
    "login.codex": ("not logged in: run codex login", "nicht angemeldet: codex login ausführen",
                    "вход не выполнен: выполните codex login"),
    "login.unknown": ("login not checked", "Anmeldung nicht geprüft", "вход не проверен"),

    # --- live mode in the console ---------------------------------------------------------------
    "live.language": ("Language of the meeting:", "Sprache der Besprechung:", "Язык встречи:"),
    "live.detect": ("don't know, detect from the first phrases", "weiß nicht, aus den ersten Sätzen erkennen",
                    "не знаю, определить по первым фразам"),
    "live.recording": ("\n=== Recording and transcribing. Press Enter to stop. ===\n",
                       "\n=== Aufnahme und Transkription laufen. Enter beendet sie. ===\n",
                       "\n=== Идёт запись и расшифровка. Нажмите Enter, чтобы остановить. ===\n"),
    "live.what_now": ("What should be done with the recording?", "Was soll mit der Aufnahme geschehen?",
                      "Что сделать с записью?"),
    "live.option_full": ("1 - process it fully: transcribe it again in one piece (better quality), and if\n"
                         "      wanted split it by speaker, check the text and make a summary",
                         "1 - vollständig verarbeiten: komplett neu transkribieren (bessere Qualität), auf\n"
                         "      Wunsch nach Sprechern trennen, Text prüfen und zusammenfassen",
                         "1 - обработать полностью: расшифровать заново целиком (лучше качество), по желанию\n"
                         "      разделить по говорящим, проверить текст и сделать выжимку"),
    "live.option_summary": ("2 - make a summary of the live text", "2 - den Live-Text zusammenfassen",
                            "2 - сделать выжимку по тексту, который получился на лету"),
    "live.nothing": ("nothing, finish", "nichts, beenden", "ничего, закончить"),
    "live.keep_sound": ("Keep the meeting sound ({file}, needed to process it again)?",
                        "Den Ton der Besprechung behalten ({file}, nötig für eine erneute Verarbeitung)?",
                        "Оставить звук встречи ({file}, нужен для повторной обработки)?"),
    "live.keep": ("1 - keep", "1 - behalten", "1 - оставить"),
    "live.delete": ("2 - delete", "2 - löschen", "2 - удалить"),
    "live.keep_default": ("keep", "behalten", "оставить"),
    "live.sound_deleted": ("Meeting sound deleted.", "Ton der Besprechung gelöscht.", "Звук встречи удалён."),
    "live.all_in": ("\nEverything is in {folder}", "\nAlles liegt in {folder}", "\nВсё лежит в {folder}"),

    # --- live window ----------------------------------------------------------------------------
    "win.title": ("Meeting transcription", "Besprechung transkribieren", "Расшифровка встречи"),
    "win.loading": ("Loading the speech recognition model...", "Lade das Spracherkennungsmodell...",
                    "Загружаю модель распознавания..."),
    "win.before": (" Before you start ", " Vor dem Start ", " Перед началом "),
    "win.interface": ("Interface language:", "Sprache der Oberfläche:", "Язык интерфейса:"),
    "win.language": ("Meeting language:", "Sprache der Besprechung:", "Язык встречи:"),
    "win.microphone": ("Microphone (your voice):", "Mikrofon (Ihre Stimme):", "Микрофон (ваш голос):"),
    "win.no_microphone": ("Do not record the microphone", "Mikrofon nicht aufnehmen", "Не записывать микрофон"),
    "win.computer": ("Computer sound\n(the other side):", "Computerton\n(die anderen):",
                     "Звук компьютера\n(собеседники):"),
    "win.all_devices": ("All devices are checked, so the other side is heard wherever the call's sound goes.",
                        "Alle Geräte sind ausgewählt, damit die anderen zu hören sind, egal wohin der Ton des Anrufs geht.",
                        "Отмечены все устройства: так собеседники будут слышны, куда бы ни шёл звук созвона."),
    "win.translate_to": ("Translate into:", "Übersetzen in:", "Переводить на:"),
    "win.translate_none": ("No translation", "Keine Übersetzung", "Без перевода"),
    "win.translate_note": ("Locally, nothing leaves the computer. The first time, the model for the "
                           "language pair is downloaded.",
                           "Lokal, nichts verlässt den Computer. Beim ersten Mal wird das Modell für "
                           "das Sprachpaar heruntergeladen.",
                           "Локально, текст никуда не уходит. В первый раз скачивается модель для "
                           "этой пары языков."),
    "win.translation_head": ("Translation ({language})", "Übersetzung ({language})", "Перевод ({language})"),
    "win.after_translate": ("Translate the text into:", "Den Text übersetzen in:", "Перевести текст на:"),
    "win.translate_local": ("(locally)", "(lokal)", "(локально)"),
    "win.check_translation": ("Check the translation with an AI: meaning, numbers, names",
                              "Übersetzung mit einer KI prüfen: Sinn, Zahlen, Namen",
                              "Проверить перевод с помощью ИИ: смысл, числа, имена"),
    "win.translation": ("translation", "Übersetzung", "Перевод"),
    "win.checked_translation": ("checked translation", "geprüfte Übersetzung", "Проверенный перевод"),
    "win.shots_of": ("Screenshots of:", "Bildschirmfotos von:", "Снимки экрана:"),
    "win.screen_n": ("Screen {n} ({w}×{h})", "Bildschirm {n} ({w}×{h})", "Экран {n} ({w}×{h})"),
    "win.screen_all": ("All screens", "Alle Bildschirme", "Все экраны"),
    "win.shots_note": ("Taken with a button during the recording and put into the text at their moment "
                       "(meeting.md). They stay on this computer.",
                       "Per Knopf während der Aufnahme, im Text an ihrer Stelle eingefügt (meeting.md). "
                       "Sie bleiben auf diesem Computer.",
                       "Делаются кнопкой во время записи и встают в текст в свой момент (meeting.md). "
                       "Остаются на этом компьютере."),
    "win.shot": ("📷  Screenshot", "📷  Bildschirmfoto", "📷  Снимок экрана"),
    "win.shots_count": ("{n} taken", "{n} aufgenommen", "сделано: {n}"),
    "win.shot_failed": ("Screenshot failed: {error}", "Bildschirmfoto fehlgeschlagen: {error}",
                        "Снимок не удался: {error}"),
    "win.text_with_shots": ("text with screenshots", "Text mit Bildschirmfotos", "Текст со снимками"),
    "win.export_html": ("Export to HTML", "Als HTML exportieren", "Экспорт в HTML"),
    "win.exporting": ("Exporting to HTML...", "Exportiere als HTML...", "Экспортирую в HTML..."),
    "win.exported": ("Exported: {files}", "Exportiert: {files}", "Готово: {files}"),
    "win.export_failed": ("Export failed: {error}", "Export fehlgeschlagen: {error}", "Экспорт не удался: {error}"),
    "win.folder": ("Folder:", "Ordner:", "Папка:"),
    "win.date_time": ("<date time>", "<Datum Uhrzeit>", "<дата время>"),
    "win.tell_people": ("Tell the participants that the meeting is transcribed.",
                        "Sagen Sie den Teilnehmenden, dass die Besprechung transkribiert wird.",
                        "Предупредите участников, что встреча расшифровывается."),
    "win.start": ("●  Start recording", "●  Aufnahme starten", "●  Начать запись"),
    "win.meter_mic": ("Microphone", "Mikrofon", "Микрофон"),
    "win.meter_computer": ("Computer sound", "Computerton", "Звук компьютера"),
    "win.silence": ("silence", "Stille", "тишина"),
    "win.mic_warning": (
        "The other side is heard, but your microphone has been silent for more than 20 seconds. Check "
        "that it is not muted (a button on the headset or in the call program) and that the same "
        "microphone is chosen here as in the call program.",
        "Die anderen sind zu hören, aber Ihr Mikrofon ist seit über 20 Sekunden still. Prüfen Sie, dass "
        "es nicht stummgeschaltet ist (Taste am Headset oder im Anrufprogramm) und dass hier dasselbe "
        "Mikrofon gewählt ist wie im Anrufprogramm.",
        "Собеседников слышно, а ваш микрофон молчит уже больше 20 секунд. Проверьте, что он не "
        "выключен (кнопка на гарнитуре или в программе созвона) и что здесь выбран тот же "
        "микрофон, что в программе созвона."),
    "win.text_hint": ("The text of the meeting will appear here.\n", "Hier erscheint der Text der Besprechung.\n",
                      "Здесь появится текст встречи.\n"),
    "win.to_end": ("↓ To the end", "↓ Zum Ende", "↓ К концу"),
    "win.stop": ("■  Stop", "■  Beenden", "■  Остановить"),
    "win.open_folder": ("Open folder", "Ordner öffnen", "Открыть папку"),
    "win.copy": ("Copy text", "Text kopieren", "Копировать текст"),
    "win.nothing_title": ("Nothing to record", "Nichts aufzunehmen", "Нечего записывать"),
    "win.nothing_text": ("Choose a microphone or at least one sound device.",
                         "Wählen Sie ein Mikrofon oder mindestens ein Tongerät.",
                         "Выберите микрофон или хотя бы одно устройство звука."),
    "win.start_failed": ("Could not start recording", "Aufnahme konnte nicht starten", "Не удалось начать запись"),
    "win.recording": ("●  Recording", "●  Aufnahme läuft", "●  Идёт запись"),
    "win.stopping": ("Stopping, writing the last phrases...", "Beende, schreibe die letzten Sätze...",
                     "Останавливаю, дописываю последние фразы..."),
    "win.stopped": ("Recording stopped: {length}", "Aufnahme beendet: {length}", "Запись остановлена: {length}"),
    "win.after": (" What next ", " Wie weiter ", " Что дальше "),
    "win.live_saved": ("Live text saved: {path}", "Live-Text gespeichert: {path}", "Текст на лету сохранён: {path}"),
    "win.redo": ("Transcribe the recording again in one piece (more accurate than live)",
                 "Aufnahme komplett neu transkribieren (genauer als live)",
                 "Расшифровать запись заново целиком (точнее, чем на лету)"),
    "win.split_call": ("Split the other side by voice, people in total:",
                       "Die anderen nach Stimme trennen, Personen insgesamt:",
                       "Разделить собеседников по голосам, всего человек:"),
    "win.split": ("Split by speaker, people:", "Nach Sprechern trennen, Personen:", "Разделить по говорящим, человек:"),
    "win.count_note_call": ("including you; 0 = don't know", "Sie mitgezählt; 0 = weiß nicht",
                            "вместе с вами; 0 = не знаю"),
    "win.count_note": ("0 = don't know", "0 = weiß nicht", "0 = не знаю"),
    "win.check": ("Check the text with an AI: names instead of numbers, phrases with the wrong speaker",
                  "Text mit einer KI prüfen: Namen statt Nummern, Sätze beim falschen Sprecher",
                  "Проверить текст с помощью ИИ: имена вместо номеров, реплики с чужой меткой"),
    "win.summary": ("Make a summary with an AI", "Zusammenfassung mit einer KI erstellen",
                    "Сделать выжимку с помощью ИИ"),
    "win.ai": ("AI:", "KI:", "ИИ:"),
    "win.searching": ("Looking for installed AIs and checking the login...",
                      "Suche installierte KIs und prüfe die Anmeldung...",
                      "Ищу установленные ИИ и проверяю вход..."),
    "win.path": ("Path to claude or codex (or their folder), or the address of a local server, "
                 "for example http://127.0.0.1:11434:",
                 "Pfad zu claude oder codex (oder deren Ordner) oder die Adresse eines lokalen Servers, "
                 "zum Beispiel http://127.0.0.1:11434:",
                 "Путь к claude или codex (или к их папке), или адрес локального сервера, "
                 "например http://127.0.0.1:11434:"),
    "win.try_path": ("Check", "Prüfen", "Проверить"),
    "win.ai_rules": ("The text goes to the chosen AI under your account (a local model keeps it on the "
                     "computer), so only if the rules you work under allow it.",
                     "Der Text geht an die gewählte KI unter Ihrem Konto (ein lokales Modell behält ihn auf "
                     "dem Computer), also nur, wenn Ihre Regeln das erlauben.",
                     "Текст уйдёт в выбранный ИИ под вашим аккаунтом (у локальной модели останется на "
                     "компьютере), поэтому только если ваши правила это разрешают."),
    "win.delete_sound": ("Delete the meeting sound (meeting.wav) after processing",
                         "Ton der Besprechung (meeting.wav) nach der Verarbeitung löschen",
                         "Удалить звук встречи (meeting.wav) после обработки"),
    "win.run": ("Run", "Ausführen", "Выполнить"),
    "win.close": ("Close", "Schließen", "Закрыть"),
    "win.no_ai": ("No AI ready to use (installed and logged in).",
                  "Keine KI einsatzbereit (installiert und angemeldet).",
                  "Нет ИИ, готового к работе (установленного и с выполненным входом)."),
    "win.not_found_title": ("Not found", "Nicht gefunden", "Не найдено"),
    "win.not_logged_title": ("Not logged in", "Nicht angemeldet", "Вход не выполнен"),
    "win.found_but": ("{title} found, but {reason}.", "{title} gefunden, aber {reason}.", "{title} найден, но {reason}."),
    "win.nothing_to_do_title": ("Nothing to do", "Nichts zu tun", "Нечего делать"),
    "win.nothing_to_do": ("Check what should be done with the recording, or press \"Close\".",
                          "Wählen Sie aus, was mit der Aufnahme geschehen soll, oder klicken Sie auf „Schließen“.",
                          "Отметьте, что сделать с записью, или нажмите «Закрыть»."),
    "win.wait_title": ("Please wait", "Bitte warten", "Подождите"),
    "win.wait": ("Still checking which AIs are installed and logged in. This takes a few seconds.",
                 "Prüfe noch, welche KIs installiert und angemeldet sind. Das dauert ein paar Sekunden.",
                 "Ещё проверяю, какие ИИ установлены и где выполнен вход. Это несколько секунд."),
    "win.no_ai_title": ("No AI", "Keine KI", "Нет ИИ"),
    "win.no_ai_text": ("The check and the summary need an AI: enter a path or uncheck them.",
                       "Prüfung und Zusammenfassung brauchen eine KI: Pfad angeben oder die Häkchen entfernen.",
                       "Для проверки и выжимки нужен ИИ: укажите путь или снимите эти галочки."),
    "win.processing": ("Processing...", "Verarbeitung...", "Обработка..."),
    "win.processing_head": ("\n\n— Processing the recording —\n", "\n\n— Verarbeitung der Aufnahme —\n",
                            "\n\n— Обработка записи —\n"),
    "win.cancel": ("■  Stop processing", "■  Verarbeitung abbrechen", "■  Остановить обработку"),
    "win.cancelling": ("Stopping the processing...", "Breche die Verarbeitung ab...", "Останавливаю обработку..."),
    "win.cancelled": ("Processing stopped", "Verarbeitung abgebrochen", "Обработка остановлена"),
    "win.cancelled_note": ("Processing stopped. Files that were already finished are kept; the meeting sound "
                           "is not deleted. Run starts it again.",
                           "Verarbeitung abgebrochen. Bereits fertige Dateien bleiben erhalten; der Ton der "
                           "Besprechung wird nicht gelöscht. „Ausführen“ startet sie erneut.",
                           "Обработка остановлена. Уже готовые файлы сохранены, звук встречи не удалён. "
                           "«Выполнить» запустит её заново."),
    "win.processing_title": ("Processing", "Verarbeitung läuft", "Идёт обработка"),
    "win.close_processing": ("Stop the processing and close the window?\nFiles that are already finished are kept.",
                             "Verarbeitung abbrechen und Fenster schließen?\nBereits fertige Dateien bleiben erhalten.",
                             "Остановить обработку и закрыть окно?\nУже готовые файлы сохранятся."),
    "win.done": ("Done", "Fertig", "Готово"),
    "win.done_errors": ("Done, with errors (see the text)", "Fertig, mit Fehlern (siehe Text)",
                        "Готово, но с ошибками (см. текст)"),
    "win.open": ("Open: {what}", "Öffnen: {what}", "Открыть: {what}"),
    "win.checked_text": ("checked text", "geprüfter Text", "Проверенный текст"),
    "win.text": ("text", "Text", "Текст"),
    "win.summary_file": ("summary", "Zusammenfassung", "Выжимку"),
    "win.ready": ("Ready to record", "Bereit zur Aufnahme", "Готово к записи"),
    "win.model_failed": ("The model did not load", "Das Modell wurde nicht geladen", "Модель не загрузилась"),
    "win.error": ("Error", "Fehler", "Ошибка"),
    "win.model_failed_text": ("The speech recognition model did not load:\n{error}\n\nRun {setup}.",
                              "Das Spracherkennungsmodell wurde nicht geladen:\n{error}\n\nFühren Sie {setup} aus.",
                              "Модель распознавания не загрузилась:\n{error}\n\nЗапустите {setup}."),
    "win.recording_title": ("Recording", "Aufnahme läuft", "Идёт запись"),
    "win.close_question": ("Stop recording and close the window?\nThe text and the sound are kept.",
                           "Aufnahme beenden und Fenster schließen?\nText und Ton bleiben erhalten.",
                           "Остановить запись и закрыть окно?\nТекст и звук сохранятся."),
    "win.stopping_short": ("Stopping...", "Beende...", "Останавливаю..."),

    # --- shortcuts and menu entries -------------------------------------------------------------
    "link.transcribe": ("Transcribe a recording", "Aufnahme transkribieren", "Расшифровать запись"),
    "link.live": ("Live meeting transcription", "Besprechung live transkribieren", "Расшифровка встречи на лету"),
    "link.setup": ("Setup and update", "Installation und Update", "Установка и обновление"),
    "link.setup_menu": ("Transcription: setup and update", "Transkription: Installation und Update",
                        "Расшифровка: установка и обновление"),
    "link.sendto": ("Transcribe", "Transkribieren", "Расшифровать"),
}


def system_language() -> str:
    """The display language of the system, if it is one of LANGUAGES; else the default."""
    code = ""
    if os.name == "nt":
        try:
            import ctypes
            primary = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF  # LANGID's primary language
            code = {0x09: "en", 0x07: "de", 0x19: "ru"}.get(primary, "")
        except (AttributeError, OSError):
            pass
    else:
        for variable in ("LC_ALL", "LC_MESSAGES", "LANG", "LANGUAGE"):
            value = os.environ.get(variable, "")
            if value and value not in ("C", "POSIX") and not value.startswith("C."):
                code = value[:2].lower()
                break
    return code if code in LANGUAGES else DEFAULT


def saved_language() -> str | None:
    settings = configparser.ConfigParser()
    settings.read(SETTINGS_FILE, encoding="utf-8")
    code = settings.get("ui", "language", fallback=None)
    return code if code in LANGUAGES else None


def save_language(code: str) -> None:
    """Remembers the language in ui.local.ini, keeping its other sections."""
    settings = configparser.ConfigParser()
    settings.read(SETTINGS_FILE, encoding="utf-8")
    if not settings.has_section("ui"):
        settings.add_section("ui")
    settings.set("ui", "language", code)
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as out:
            settings.write(out)
    except OSError:
        pass  # only a convenience


def set_language(code: str) -> None:
    global _current
    _current = code if code in LANGUAGES else DEFAULT


def shortcuts_language() -> str | None:
    """The language of the shortcuts already in the tool folder (Windows), so an installation
    from before the interface had a choice stays in the language its users know."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for code in LANGUAGES:
        if os.path.isfile(os.path.join(root, text_in(code, "link.transcribe") + ".lnk")):
            return code
    return None


def language() -> str:
    if _current is None:
        code = saved_language()
        if code is None:
            code = shortcuts_language()
            if code:
                save_language(code)  # from now on a choice like any other
        set_language(code or system_language())
    return _current


def t(key: str, **values) -> str:
    text = TEXTS[key][list(LANGUAGES).index(language())]
    return text.format(**values) if values else text


def text_in(code: str, key: str) -> str:
    """A text in a given language, e.g. to find the shortcuts made in another one."""
    return TEXTS[key][list(LANGUAGES).index(code)]


def meeting_languages() -> list[tuple[str, str]]:
    """(code, name) of the meeting languages offered, the interface language first."""
    order = [language()] + [code for code in ("en", "de", "ru", "fr") if code != language()]
    return [(code, t("meeting." + code)) for code in order] + [("multi", t("meeting.multi"))]
