---
description: PNG/image manipulation with ImageMagick/sips
---

# Image Manipulation

Transform, resize, and prepare images for web/icons.

## Tools

- `magick` (ImageMagick) - full-featured, cross-platform
- `sips` (macOS) - quick metadata/resizing

## Common Patterns

### Check Dimensions

```bash
sips -g all image.png
# or
magick identify image.png
```

### Pad to Square (preserve aspect)

Center image with padding to make square:

```bash
# White background
magick input.png -background white -gravity center -extent 1000x1000 output.png

# Transparent background
magick input.png -background transparent -gravity center -extent 1000x1000 output.png

# Match largest dimension
magick input.png -background white -gravity center -extent "%[fx:max(w,h)]x%[fx:max(w,h)]" output.png
```

### Resize

```bash
# Exact size
magick input.png -resize 180x180 output.png

# Fit within bounds (preserve aspect)
magick input.png -resize 180x180\> output.png

# sips alternative
sips -z 180 180 input.png --out output.png
```

### Generate Icon Set

Standard favicon/touch-icon sizes:

```bash
magick source.png -resize 180x180 apple-touch-icon.png
magick source.png -resize 32x32 favicon-32.png
magick source.png -resize 16x16 favicon-16.png
```

### Convert Format

```bash
magick input.png output.webp
magick input.jpg -quality 85 output.png
```

### Batch Process

```bash
for f in *.png; do magick "$f" -resize 50% "resized/$f"; done
```

## Icon HTML

```html
<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">
<link rel="icon" type="image/png" sizes="16x16" href="/favicon-16.png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
```
