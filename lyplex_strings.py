"""
lyplex_strings.py — UI strings for English and Latin American Spanish.
Access via S(key) in lyplex_gui.py.
"""

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # Window
        "window_title": "LyPlex — Scrolling Sheet Music",
        "status_ready": "Ready.",
        "status_encoding": "Encoding…",
        "status_cancelling": "Cancelling…",
        "status_cancelled": "Cancelled.",
        "status_done": "Done: {filename}",
        "status_encoding_failed": "Encoding failed.",

        # File / folder row labels
        "label_ly_file": "LilyPond score (.ly):",
        "hint_ly_file": "(sheet music source)",
        "label_sf2": "Soundfont (.sf2):",
        "hint_sf2": "(instrument samples for audio)",
        "label_lilypond_bin": "LilyPond binary:",
        "hint_lilypond_bin": "(blank = use system PATH)",
        "label_ffmpeg_bin": "ffmpeg binary:",
        "hint_ffmpeg_bin": "(blank = use system PATH)",
        "label_fluidsynth_bin": "fluidsynth binary:",
        "hint_fluidsynth_bin": "(blank = use system PATH)",
        "label_output_folder": "Output folder:",
        "hint_output_folder": "(where to save the MP4)",

        # File dialog wildcards
        "wildcard_ly":     "LilyPond files (*.ly)|*.ly|All files (*.*)|*.*",
        "wildcard_sf2":    "Soundfont files (*.sf2)|*.sf2|All files (*.*)|*.*",
        "wildcard_exe":    "Executables (*.exe)|*.exe|All files (*.*)|*.*",
        "wildcard_images": "Images (*.svg;*.png;*.jpg;*.jpeg)|*.svg;*.png;*.jpg;*.jpeg|All files (*.*)|*.*",

        # Shared button labels
        "btn_browse":           "Browse…",
        "btn_encode_mp4":       "Encode MP4",
        "btn_cancel":           "Cancel",
        "btn_help":             "Help",
        "btn_click_settings":   "Click settings…",
        "btn_branding_settings":"Branding settings…",
        "btn_open_mp4":         "Open MP4",
        "btn_open_folder":      "Open Folder",

        # Numeric rows
        "label_resolution":    "Resolution (W × H):",
        "label_resolution_x":  " × ",
        "label_frame_rate":    "Frame rate (fps):",
        "label_target_bpm":    "Target BPM:",
        "hint_target_bpm":     "(0 = use score tempo)",

        # Overlay / option rows
        "label_fit_to_height":   "Fit to height:",
        "chk_fit_to_height":     "Pad strip to output height (centres content, white background)",

        "label_playback_cursor": "Playback cursor:",
        "chk_playback_cursor":   "Show vertical cursor line",
        "label_cursor_color":    "Cursor color:",
        "label_cursor_width":    "Cursor width (px):",

        "label_note_highlight":  "Note highlight:",
        "chk_note_highlight":    "Flash active note/chord",
        "label_highlight_color": "Highlight color:",

        "label_note_trail":      "Note trail:",
        "chk_note_trail":        "Show fading dot trail + played-region tint",

        "label_title_overlay":   "Title overlay:",
        "chk_title_overlay":     "Show title / composer (fixed, does not scroll)",
        "hint_title_overlay":    r"(from \header in .ly)",

        "label_footer_overlay":  "Footer overlay:",
        "chk_footer_overlay":    "Show copyright / tagline (fixed, does not scroll)",
        "hint_footer_overlay":   r"(from \header in .ly)",

        "label_bar_timing":      "Bar timing:",
        "chk_bar_timing":        "Scroll one step per bar (smoother for fast passages)",

        "label_bar_numbers":     "Bar numbers:",
        "chk_bar_numbers":       "Show bar number above every bar line",

        "label_metronome":       "Metronome click:",
        "chk_metronome":         "Include audio click track",

        "label_watermark":       "Watermark:",
        "watermark_none":        "(none)",

        "label_fade_frames":     "Fade in/out (frames):",
        "hint_fade_frames":      "(0 = no fade, 15 = 0.5s at 30fps)",

        "label_music_volume":    "Music volume (dB):",
        "hint_music_volume":     "dB boost applied to output mix",

        "label_auto_open":       "Auto-open MP4:",
        "chk_auto_open":         "Open video in default player when encoding completes",

        # Log area
        "label_log":             "Log:",
        "log_accessible_name":   "Pipeline output log",

        # Log / status messages
        "log_cancelled":         "\nCancelled.",
        "log_done":              "\nDone: {path}",
        "log_encoding_failed":   "\nEncoding failed. See log above.",
        "log_error":             "\nERROR: {exc}",

        # Validation MessageBox
        "msg_select_ly":             "Select a valid .ly file.",
        "msg_select_sf2":            "Select a valid .sf2 soundfont.",
        "msg_select_output_folder":  "Select an output folder.",
        "msg_even_resolution":       "Width and height must both be even numbers (ffmpeg requirement).",
        "msg_input_required_title":  "Input required",
        "msg_invalid_res_title":     "Invalid resolution",
        "msg_cannot_open_mp4_title": "Could not open MP4",

        # --- MetronomeDialog ---
        "metro_dialog_title":       "Metronome Settings",
        "metro_section_accent":     "Accent click  (beat 1)",
        "metro_section_beat":       "Beat click  (beats 2, 3, …)",
        "metro_section_count_in":   "Count-in",
        "metro_section_mix":        "Mix level",
        "metro_label_frequency":    "Frequency:",
        "metro_hint_frequency":     "Hz",
        "metro_label_waveform":     "Waveform:",
        "metro_label_duration":     "Duration:",
        "metro_hint_duration":      "ms",
        "metro_label_amplitude":    "Amplitude:",
        "metro_hint_amplitude":     "0.05 – 1.0",
        "metro_label_bars":         "Bars:",
        "metro_hint_count_in_bars": "0 = no count-in",
        "metro_label_click_volume": "Click volume:",
        "metro_hint_click_volume":  "dB  (relative to music)",

        # --- WatermarkDialog ---
        "wm_dialog_title":   "Watermark Settings",
        "wm_label_logo":     "Logo file:",
        "wm_hint_logo":      "(blank = no watermark)",
        "wm_label_position": "Position:",
        "wm_hint_position":  "corner of video",
        "wm_label_opacity":  "Opacity:",
        "wm_hint_opacity":   "0.05 – 1.0",

        # Accessibility names (screen readers)
        "accessible_video_width":   "Video width",
        "accessible_video_height":  "Video height",
        "accessible_frame_rate":    "Frame rate",
        "accessible_cursor_width":  "Cursor width",
        "accessible_metronome":     "Metronome click enabled",
        "accessible_fade_frames":   "Fade frames",
        "accessible_music_volume":  "Music volume dB",

        # File / folder dialog titles
        "dlg_open_file":   "Open file",
        "dlg_open_folder": "Open folder",

        # Waveform display names (MetronomeDialog Choice)
        "waveform_sine":     "Sine",
        "waveform_square":   "Square",
        "waveform_triangle": "Triangle",
        "waveform_saw":      "Sawtooth",

        # Color preset display names
        "color_red":    "Red",
        "color_blue":   "Blue",
        "color_green":  "Green",
        "color_yellow": "Yellow",
        "color_cyan":   "Cyan",
        "color_orange": "Orange",
        "color_white":  "White",
        "color_black":  "Black",
        "color_purple": "Purple",
        "color_pink":   "Pink",
    },

    "es": {
        # Ventana
        "window_title": "LyPlex — Partitura Desplazable",
        "status_ready": "Listo.",
        "status_encoding": "Codificando…",
        "status_cancelling": "Cancelando…",
        "status_cancelled": "Cancelado.",
        "status_done": "Listo: {filename}",
        "status_encoding_failed": "Error al codificar.",

        # Filas de archivos / carpeta
        "label_ly_file": "Partitura LilyPond (.ly):",
        "hint_ly_file": "(fuente de la partitura)",
        "label_sf2": "Soundfont (.sf2):",
        "hint_sf2": "(muestras de instrumentos para el audio)",
        "label_lilypond_bin": "Ejecutable de LilyPond:",
        "hint_lilypond_bin": "(en blanco = usar PATH del sistema)",
        "label_ffmpeg_bin": "Ejecutable de ffmpeg:",
        "hint_ffmpeg_bin": "(en blanco = usar PATH del sistema)",
        "label_fluidsynth_bin": "Ejecutable de fluidsynth:",
        "hint_fluidsynth_bin": "(en blanco = usar PATH del sistema)",
        "label_output_folder": "Carpeta de salida:",
        "hint_output_folder": "(dónde guardar el MP4)",

        # Filtros de diálogos
        "wildcard_ly":     "Archivos LilyPond (*.ly)|*.ly|Todos los archivos (*.*)|*.*",
        "wildcard_sf2":    "Archivos Soundfont (*.sf2)|*.sf2|Todos los archivos (*.*)|*.*",
        "wildcard_exe":    "Ejecutables (*.exe)|*.exe|Todos los archivos (*.*)|*.*",
        "wildcard_images": "Imágenes (*.svg;*.png;*.jpg;*.jpeg)|*.svg;*.png;*.jpg;*.jpeg|Todos los archivos (*.*)|*.*",

        # Botones compartidos
        "btn_browse":            "Explorar…",
        "btn_encode_mp4":        "Codificar MP4",
        "btn_cancel":            "Cancelar",
        "btn_help":              "Ayuda",
        "btn_click_settings":    "Ajustes de click…",
        "btn_branding_settings": "Ajustes de marca…",
        "btn_open_mp4":          "Abrir MP4",
        "btn_open_folder":       "Abrir carpeta",

        # Filas numéricas
        "label_resolution":    "Resolución (A × H):",
        "label_resolution_x":  " × ",
        "label_frame_rate":    "Fotogramas por segundo (fps):",
        "label_target_bpm":    "BPM objetivo:",
        "hint_target_bpm":     "(0 = usar el tempo de la partitura)",

        # Casillas de opciones
        "label_fit_to_height":   "Ajustar a la altura:",
        "chk_fit_to_height":     "Rellenar la tira al alto de salida (centra el contenido, fondo blanco)",

        "label_playback_cursor": "Cursor de reproducción:",
        "chk_playback_cursor":   "Mostrar línea vertical de cursor",
        "label_cursor_color":    "Color del cursor:",
        "label_cursor_width":    "Ancho del cursor (px):",

        "label_note_highlight":  "Resaltado de nota:",
        "chk_note_highlight":    "Iluminar la nota/acorde activo",
        "label_highlight_color": "Color de resaltado:",

        "label_note_trail":      "Rastro de nota:",
        "chk_note_trail":        "Mostrar rastro de puntos con fundido + tinte en región tocada",

        "label_title_overlay":   "Superposición de título:",
        "chk_title_overlay":     "Mostrar título / compositor (fijo, no se desplaza)",
        "hint_title_overlay":    r"(de \header en el .ly)",

        "label_footer_overlay":  "Superposición de pie de página:",
        "chk_footer_overlay":    "Mostrar copyright / eslogan (fijo, no se desplaza)",
        "hint_footer_overlay":   r"(de \header en el .ly)",

        "label_bar_timing":      "Sincronía por compás:",
        "chk_bar_timing":        "Desplazar un paso por compás (más suave en pasajes rápidos)",

        "label_bar_numbers":     "Números de compás:",
        "chk_bar_numbers":       "Mostrar número de compás sobre cada línea divisoria",

        "label_metronome":       "Click de metrónomo:",
        "chk_metronome":         "Incluir pista de clic de audio",

        "label_watermark":       "Marca de agua:",
        "watermark_none":        "(ninguna)",

        "label_fade_frames":     "Fundido de entrada/salida (fotogramas):",
        "hint_fade_frames":      "(0 = sin fundido, 15 = 0.5s a 30fps)",

        "label_music_volume":    "Volumen de música (dB):",
        "hint_music_volume":     "Incremento en dB aplicado a la mezcla de salida",

        "label_auto_open":       "Abrir MP4 automáticamente:",
        "chk_auto_open":         "Abrir el video en el reproductor predeterminado al terminar",

        # Área de registro
        "label_log":           "Registro:",
        "log_accessible_name": "Registro de salida del proceso",

        # Mensajes de registro / estado
        "log_cancelled":       "\nCancelado.",
        "log_done":            "\nListo: {path}",
        "log_encoding_failed": "\nError al codificar. Consulta el registro anterior.",
        "log_error":           "\nERROR: {exc}",

        # Mensajes de validación
        "msg_select_ly":             "Selecciona un archivo .ly válido.",
        "msg_select_sf2":            "Selecciona un soundfont .sf2 válido.",
        "msg_select_output_folder":  "Selecciona una carpeta de salida.",
        "msg_even_resolution":       "El ancho y alto deben ser números pares (requisito de ffmpeg).",
        "msg_input_required_title":  "Campo requerido",
        "msg_invalid_res_title":     "Resolución inválida",
        "msg_cannot_open_mp4_title": "No se pudo abrir el MP4",

        # --- MetronomeDialog ---
        "metro_dialog_title":       "Ajustes del metrónomo",
        "metro_section_accent":     "Click acentuado  (tiempo 1)",
        "metro_section_beat":       "Click de tiempo  (tiempos 2, 3, …)",
        "metro_section_count_in":   "Cuenta de entrada",
        "metro_section_mix":        "Nivel de mezcla",
        "metro_label_frequency":    "Frecuencia:",
        "metro_hint_frequency":     "Hz",
        "metro_label_waveform":     "Forma de onda:",
        "metro_label_duration":     "Duración:",
        "metro_hint_duration":      "ms",
        "metro_label_amplitude":    "Amplitud:",
        "metro_hint_amplitude":     "0.05 – 1.0",
        "metro_label_bars":         "Compases:",
        "metro_hint_count_in_bars": "0 = sin cuenta de entrada",
        "metro_label_click_volume": "Volumen del click:",
        "metro_hint_click_volume":  "dB  (relativo a la música)",

        # --- WatermarkDialog ---
        "wm_dialog_title":   "Ajustes de marca de agua",
        "wm_label_logo":     "Archivo de logo:",
        "wm_hint_logo":      "(en blanco = sin marca de agua)",
        "wm_label_position": "Posición:",
        "wm_hint_position":  "esquina del video",
        "wm_label_opacity":  "Opacidad:",
        "wm_hint_opacity":   "0.05 – 1.0",

        # Nombres accesibles (lectores de pantalla)
        "accessible_video_width":   "Ancho del video",
        "accessible_video_height":  "Alto del video",
        "accessible_frame_rate":    "Fotogramas por segundo",
        "accessible_cursor_width":  "Ancho del cursor",
        "accessible_metronome":     "Click de metrónomo activado",
        "accessible_fade_frames":   "Fotogramas de fundido",
        "accessible_music_volume":  "Volumen de música en dB",

        # Títulos de diálogos de archivo / carpeta
        "dlg_open_file":   "Abrir archivo",
        "dlg_open_folder": "Abrir carpeta",

        # Nombres de formas de onda (MetronomeDialog)
        "waveform_sine":     "Seno",
        "waveform_square":   "Cuadrada",
        "waveform_triangle": "Triangular",
        "waveform_saw":      "Sierra",

        # Nombres de colores
        "color_red":    "Rojo",
        "color_blue":   "Azul",
        "color_green":  "Verde",
        "color_yellow": "Amarillo",
        "color_cyan":   "Cian",
        "color_orange": "Naranja",
        "color_white":  "Blanco",
        "color_black":  "Negro",
        "color_purple": "Morado",
        "color_pink":   "Rosa",
    },
}
