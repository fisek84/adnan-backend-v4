import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { deflateSync } from "node:zlib";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Minimal PNG generator (solid RGBA) using only Node core modules.

const PNG_SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

function crc32(buffer) {
  let crc = 0xffffffff;
  for (let i = 0; i < buffer.length; i++) {
    crc ^= buffer[i];
    for (let j = 0; j < 8; j++) {
      const mask = -(crc & 1);
      crc = (crc >>> 1) ^ (0xedb88320 & mask);
    }
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const typeBuf = Buffer.from(type, "ascii");
  const lengthBuf = Buffer.alloc(4);
  lengthBuf.writeUInt32BE(data.length, 0);

  const crcBuf = Buffer.alloc(4);
  const crcVal = crc32(Buffer.concat([typeBuf, data]));
  crcBuf.writeUInt32BE(crcVal, 0);

  return Buffer.concat([lengthBuf, typeBuf, data, crcBuf]);
}

function pngSolid({ width, height, rgba }) {
  const [r, g, b, a] = rgba;
  const rowLength = 1 + width * 4; // filter byte + pixels
  const raw = Buffer.alloc(rowLength * height);

  for (let y = 0; y < height; y++) {
    const rowStart = y * rowLength;
    raw[rowStart] = 0; // filter type 0
    for (let x = 0; x < width; x++) {
      const i = rowStart + 1 + x * 4;
      raw[i] = r;
      raw[i + 1] = g;
      raw[i + 2] = b;
      raw[i + 3] = a;
    }
  }

  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // color type RGBA
  ihdr[10] = 0; // compression
  ihdr[11] = 0; // filter
  ihdr[12] = 0; // interlace

  const idat = deflateSync(raw, { level: 9 });

  return Buffer.concat([
    PNG_SIGNATURE,
    chunk("IHDR", ihdr),
    chunk("IDAT", idat),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

async function main() {
  const publicDir = join(__dirname, "..", "public");
  await mkdir(publicDir, { recursive: true });

  // Dark background + slightly lighter accent for maskable (still safe).
  const base = { rgba: [11, 18, 32, 255] };
  const maskable = { rgba: [15, 23, 42, 255] };

  const outputs = [
    { file: "icon-192.png", width: 192, height: 192, ...base },
    { file: "icon-512.png", width: 512, height: 512, ...base },
    { file: "icon-192-maskable.png", width: 192, height: 192, ...maskable },
    { file: "icon-512-maskable.png", width: 512, height: 512, ...maskable },
    { file: "apple-touch-icon.png", width: 180, height: 180, ...base },
    { file: "favicon-32.png", width: 32, height: 32, ...base },
    { file: "favicon-16.png", width: 16, height: 16, ...base },
  ];

  await Promise.all(
    outputs.map(async (o) => {
      const buf = pngSolid({ width: o.width, height: o.height, rgba: o.rgba });
      await writeFile(join(publicDir, o.file), buf);
      process.stdout.write(`[pwa-icons] wrote ${o.file}\n`);
    })
  );
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
