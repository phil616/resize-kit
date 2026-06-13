# 命令行用法

```bash
# 把照片压进 150–200 KiB 区间
resize-kit compress photo.jpg --min 150KB --max 200KB -o photo.small.jpg

# 压缩到原始大小的一半
resize-kit compress slides.pptx --ratio 0.5

# 命中精确体积（±50 KiB 容差），用于满足上传限制
resize-kit compress clip.mp4 --exact 8MB --tolerance 50KB

# 把扫描版 PDF 整页栅格化以获得最大压缩
resize-kit compress scan.pdf --max 1MB --pdf-mode rasterize

# 在不改动任何像素的前提下，把图像增大到正好 900 KiB
resize-kit inflate icon.png --to 900KB

# 查看 resize-kit 的识别结果
resize-kit probe movie.mkv
resize-kit doctor
```

体积单位支持 `B`、`KB`/`KiB`、`MB`/`MiB`、`GB`/`GiB`（KB == KiB == 1024）。

**退出码：** `0` 落入区间 · `2` 目标不可达 · `3` 已完成但超出区间 · `1` 出错。

## 主要选项

| 选项 | 含义 |
|---|---|
| `--ratio R` | 压缩到原始大小的比例 `R`（0–1） |
| `--max / --min` | 体积区间上 / 下界（任一可省略） |
| `--exact S` | 精确目标体积，配合 `--tolerance` 使用 |
| `--inflate S` | 通过无损填充把文件增大到体积 `S` |
| `--pdf-mode` | `multimedia`（保留文字/矢量）或 `rasterize`（仅图像） |
| `--png-alpha` | 透明 PNG 后端：`quantize`（默认）或 `channel_split` |
| `--keep-ooxml` | DOC/PPT 直接输出 DOCX/PPTX（更稳妥、可精确控制体积） |
| `--no-downscale` | 禁止降分辨率 / 降采样率 |
| `--no-pad` | 禁止通过填充达到下界 |
