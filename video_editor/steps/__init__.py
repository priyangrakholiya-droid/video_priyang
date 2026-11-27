"""The pipeline steps, in the order you run them.

1. select   - pick what to keep out of the footage          -> 02_selected/
2. arrange  - decide which clip follows which clip          -> 03_arranged/
3. music    - find the song's beats and snap the cuts to them -> 04_music/
4. emotions - sort clips into emotion folders               -> 05_emotion/
5. render   - merge it all into the finished film           -> 06_final/
"""

from video_editor.steps import arrange, emotions, music, render, select

__all__ = ["select", "arrange", "music", "emotions", "render"]
