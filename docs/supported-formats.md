# 支持的格式

| 输入 | 处理路径 |
|---|---|
| JPEG/PNG/BMP/GIF/TIFF/WEBP | 有损重编码；保留 alpha 通道 |
| MP3/AAC/M4A/OGG/OPUS/FLAC/WAV | ffmpeg，编码格式不变，码率/质量旋钮 |
| MP4/MKV/MOV/WEBM/AVI | ffmpeg，容器不变，CRF 旋钮 |
| DOCX/PPTX/XLSX | 解压 → 压缩媒体 → 重新打包（零结构变更） |
| DOC/PPT | LibreOffice → DOCX/PPTX → 压缩 → 转回原格式 |
| PDF | 多媒体模式（保留文字/矢量）**或** 栅格化模式（仅图像） |
