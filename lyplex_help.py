"""
lyplex_help.py — bilingual help content for the LyPlex Help dialog.
Latin American Spanish / English.
"""

HELP: dict[str, dict] = {
    "en": {
        "title": "LyPlex Help",
        "sections": [
            {
                "heading": "Getting Started",
                "body": (
                    "LyPlex converts a LilyPond score (.ly file) into a scrolling MP4 video "
                    "with synchronized audio.\n\n"
                    "Steps:\n"
                    "  1. Pick your .ly file using Browse next to the Score field.\n"
                    "  2. Pick an SF2 soundfont — the instrument bank used for audio.\n"
                    "  3. Set the output folder and resolution.\n"
                    "  4. Click Encode MP4.\n\n"
                    "LyPlex compiles the score, builds a timing map, renders frames, "
                    "synthesizes audio, and muxes the final video automatically.\n\n"
                    "Required external programs: LilyPond 2.24, ffmpeg, and FluidSynth "
                    "must be installed and on your system PATH (or set explicitly in the "
                    "binary fields). LyPlex reports missing binaries before the pipeline starts."
                ),
            },
            {
                "heading": "Score Requirements",
                "body": (
                    "Your .ly file must contain:\n\n"
                    "  1. A \\version declaration at the top:\n"
                    "       \\version \"2.24.0\"\n\n"
                    "  2. A \\midi {} block inside \\score. This produces the MIDI file "
                    "LyPlex uses to calculate scroll timing. Without it the pipeline aborts.\n\n"
                    "You do NOT need to add a paper block — LyPlex injects the single-strip "
                    "layout (wide paper, one system) into a temporary copy of your file. "
                    "Your original file is never modified.\n\n"
                    "Ties (~) and \\repeat volta are handled automatically."
                ),
            },
            {
                "heading": "Overlays",
                "body": (
                    "Visual elements drawn on the scrolling score:\n\n"
                    "  Cursor — vertical line at the current playback position.\n\n"
                    "  Note highlight — colored dot drawn on each notehead as it plays. "
                    "Set color in the Highlight color row.\n\n"
                    "  Trail — fading dots left behind the highlight showing recently "
                    "played positions.\n\n"
                    "  Bar numbers — small measure numbers printed above the staff. "
                    "Useful for rehearsal reference.\n\n"
                    "  Title / Footer — text from \\header in your .ly (title, composer, "
                    "copyright) drawn as a fixed band at the top or bottom.\n\n"
                    "  Watermark — semi-transparent logo image in a corner of the frame. "
                    "Configure file, position, and opacity in Branding settings."
                ),
            },
            {
                "heading": "Metronome",
                "body": (
                    "Adds an audible click track mixed into the video audio. "
                    "Open Click settings to configure:\n\n"
                    "  Waveform — sine, square, triangle, or sawtooth.\n\n"
                    "  Accent click (beat 1) — higher frequency and louder amplitude "
                    "to mark the downbeat clearly.\n\n"
                    "  Beat click (beats 2, 3, …) — remaining beats in each measure.\n\n"
                    "  Count-in — adds one to four bars of clicks before the music starts, "
                    "giving performers time to prepare. The scroll automatically offsets "
                    "to stay in sync with the count-in.\n\n"
                    "  Click volume — adjusts the click level in dB relative to the music."
                ),
            },
            {
                "heading": "Audio & Tempo",
                "body": (
                    "  Soundfont — LyPlex uses FluidSynth to render audio from MIDI. "
                    "Supply any General MIDI .sf2 file. GeneralUser GS is a good free option.\n\n"
                    "  Music volume — gain applied to the output in dB. "
                    "0 dB = unity. Positive boosts, negative reduces.\n\n"
                    "  Target BPM — overrides the score tempo. Both audio and scroll "
                    "timing scale together so they stay in sync. Requires \\tempo in the .ly. "
                    "Set to 0 to use the score's own tempo.\n\n"
                    "  Fade in/out — number of frames to fade from/to black at the "
                    "start and end of the video. 15 frames = 0.5 s at 30 fps."
                ),
            },
            {
                "heading": "Troubleshooting",
                "body": (
                    "No \\version found\n"
                    "  Add \\version \"2.24.0\" at the top of your .ly file.\n\n"
                    "No MIDI output / timing map empty\n"
                    "  Add \\midi {} inside your \\score block.\n\n"
                    "Binary not found (lilypond / ffmpeg / fluidsynth)\n"
                    "  Install the program and add it to your system PATH, or set the "
                    "path explicitly in the binary fields, then try again.\n\n"
                    "No note anchors found in SVG\n"
                    "  Your score may have no note events, or the \\score block structure "
                    "is unexpected. Check the log for LilyPond warnings.\n\n"
                    "Timing mismatch warning\n"
                    "  Logged when SVG anchor count differs from MIDI event count. "
                    "The video still renders but scroll sync may drift slightly on scores "
                    "with many grace notes or tone clusters."
                ),
            },
        ],
    },

    "es": {
        "title": "Ayuda de LyPlex",
        "sections": [
            {
                "heading": "Primeros pasos",
                "body": (
                    "LyPlex convierte una partitura de LilyPond (archivo .ly) en un video MP4 "
                    "con desplazamiento horizontal sincronizado con el audio.\n\n"
                    "Pasos:\n"
                    "  1. Selecciona tu archivo .ly con Explorar junto al campo Partitura.\n"
                    "  2. Selecciona un soundfont SF2 — el banco de instrumentos para el audio.\n"
                    "  3. Elige la carpeta de salida y la resolución.\n"
                    "  4. Haz clic en Codificar MP4.\n\n"
                    "LyPlex compila la partitura, construye el mapa de tiempos, genera los "
                    "fotogramas, sintetiza el audio y produce el video final de forma automática.\n\n"
                    "Programas externos requeridos: LilyPond 2.24, ffmpeg y FluidSynth deben "
                    "estar instalados y disponibles en el PATH del sistema (o configurados en los "
                    "campos de ejecutables). LyPlex avisa si falta alguno antes de iniciar."
                ),
            },
            {
                "heading": "Requisitos de la partitura",
                "body": (
                    "Tu archivo .ly debe contener:\n\n"
                    "  1. Una declaración \\version al inicio:\n"
                    "       \\version \"2.24.0\"\n\n"
                    "  2. Un bloque \\midi {} dentro de \\score. Esto genera el archivo MIDI "
                    "que LyPlex usa para calcular el sincronismo. Sin él, el proceso se detiene.\n\n"
                    "NO es necesario agregar un bloque de papel — LyPlex inyecta el diseño de "
                    "tira horizontal (papel ancho, un solo sistema) en una copia temporal de tu "
                    "archivo. Tu archivo original nunca se modifica.\n\n"
                    "Las ligaduras de prolongación (~) y \\repeat volta se gestionan automáticamente."
                ),
            },
            {
                "heading": "Superposiciones",
                "body": (
                    "Elementos visuales dibujados sobre la partitura en movimiento:\n\n"
                    "  Cursor — línea vertical en la posición de reproducción actual.\n\n"
                    "  Resaltado de nota — punto de color sobre cada nota al sonar. "
                    "El color se configura en la fila Color de resaltado.\n\n"
                    "  Rastro — puntos con fundido que muestran las posiciones tocadas "
                    "recientemente.\n\n"
                    "  Números de compás — números de compás impresos sobre el pentagrama. "
                    "Útil como referencia de ensayo.\n\n"
                    "  Título / Pie de página — texto de \\header en tu .ly (título, compositor, "
                    "copyright) dibujado en una banda fija arriba o abajo del video.\n\n"
                    "  Marca de agua — imagen semitransparente en una esquina del fotograma. "
                    "Configura el archivo, posición y opacidad en Ajustes de marca."
                ),
            },
            {
                "heading": "Metrónomo",
                "body": (
                    "Agrega una pista de click audible mezclada al audio del video. "
                    "Abre Ajustes de click para configurar:\n\n"
                    "  Forma de onda — seno, cuadrada, triangular o sierra.\n\n"
                    "  Click acentuado (tiempo 1) — frecuencia más alta y mayor amplitud "
                    "para marcar claramente el tiempo fuerte.\n\n"
                    "  Click de tiempo (tiempos 2, 3, …) — tiempos restantes de cada compás.\n\n"
                    "  Cuenta de entrada — agrega de uno a cuatro compases de clicks antes de "
                    "que comience la música. El desplazamiento se compensa automáticamente para "
                    "permanecer sincronizado con la cuenta de entrada.\n\n"
                    "  Volumen del click — ajusta el nivel del click en dB relativo a la música."
                ),
            },
            {
                "heading": "Audio y Tempo",
                "body": (
                    "  Soundfont — LyPlex usa FluidSynth para sintetizar el audio desde MIDI. "
                    "Proporciona cualquier archivo .sf2 de MIDI General. "
                    "GeneralUser GS es una buena opción gratuita.\n\n"
                    "  Volumen de música — ganancia aplicada a la salida en dB. "
                    "0 dB = ganancia original. Valores positivos aumentan, negativos reducen.\n\n"
                    "  BPM objetivo — anula el tempo de la partitura. El audio y el "
                    "desplazamiento se escalan juntos para mantenerse sincronizados. "
                    "Requiere \\tempo en el .ly. Pon 0 para usar el tempo original.\n\n"
                    "  Fundido de entrada/salida — fotogramas de fundido desde/hacia negro al "
                    "inicio y al final del video. 15 fotogramas = 0.5 s a 30 fps."
                ),
            },
            {
                "heading": "Solución de problemas",
                "body": (
                    "No se encontró \\version\n"
                    "  Agrega \\version \"2.24.0\" al inicio de tu archivo .ly.\n\n"
                    "Sin salida MIDI / mapa de tiempos vacío\n"
                    "  Agrega \\midi {} dentro de tu bloque \\score.\n\n"
                    "Programa no encontrado (lilypond / ffmpeg / fluidsynth)\n"
                    "  Instala el programa y agrégalo al PATH del sistema, o configura la "
                    "ruta en los campos de ejecutables, y vuelve a intentarlo.\n\n"
                    "Sin anclajes de nota en el SVG\n"
                    "  Es posible que la partitura no tenga eventos de nota, o que la "
                    "estructura del bloque \\score sea inesperada. Revisa el registro.\n\n"
                    "Advertencia de desajuste de tiempos\n"
                    "  Se registra cuando la cantidad de anclajes SVG no coincide con la de "
                    "eventos MIDI. El video se genera de todas formas, pero la sincronía puede "
                    "desviarse levemente en partituras con muchas notas de adorno o clusters."
                ),
            },
        ],
    },
}
