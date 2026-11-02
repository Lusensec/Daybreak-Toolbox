import { md5 as jsMd5 } from "js-md5";

/**
 * 编解码纯函数（1:1 复刻 encryption.py，纯前端、无网络依赖，可独立单测）。
 * 例外：MD5 用纯 JS 实现（Web Crypto 不支持 MD5）；"乱码修复"走 bridge（外部 ASP 服务）。
 */

// ===================== Base64 =====================
export function base64Encode(text: string): string {
  const bytes = new TextEncoder().encode(text);
  let bin = "";
  bytes.forEach((b) => (bin += String.fromCharCode(b)));
  return btoa(bin);
}
export function base64Decode(text: string): string {
  const bin = atob(text);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new TextDecoder().decode(bytes);
}

// ===================== URL =====================
export function urlEncode(text: string): string {
  return encodeURIComponent(text);
}
export function urlDecode(text: string): string {
  return decodeURIComponent(text);
}

// ===================== Unicode =====================
export function unicodeEncode(text: string): string {
  // 与 encryption.unicode_encode 一致：每字符 \uXXXX（4 位十六进制）
  let out = "";
  for (const ch of text) {
    const cp = ch.codePointAt(0)!;
    if (cp < 0x10000) {
      out += "\\u" + cp.toString(16).padStart(4, "0");
    } else {
      const u = cp - 0x10000;
      out += "\\u" + (0xd800 + (u >> 10)).toString(16).padStart(4, "0");
      out += "\\u" + (0xdc00 + (u & 0x3ff)).toString(16).padStart(4, "0");
    }
  }
  return out;
}
export function unicodeDecode(text: string): string {
  return text.replace(/\\u([0-9a-fA-F]{4})/g, (_, h) =>
    String.fromCharCode(parseInt(h, 16))
  );
}

// ===================== JSON 格式化 =====================
export function jsonFormat(text: string): string {
  const t = text.trim();
  try {
    return JSON.stringify(JSON.parse(t), null, 4);
  } catch {
    try {
      const pyToJs = t
        .replace(/\bTrue\b/g, "true")
        .replace(/\bFalse\b/g, "false")
        .replace(/\bNone\b/g, "null")
        .replace(/'/g, '"');
      return JSON.stringify(JSON.parse(pyToJs), null, 4);
    } catch {
      return `无法解析为标准 JSON / Python 字面量。请确认输入是合法 JSON。\n（已拒绝执行任意表达式以保障安全）\n原文：${t.slice(0, 80)}`;
    }
  }
}

// ===================== MD5（js-md5，RFC 标准，UTF-8 安全）=====================
// 不再手抄位运算（易错）；用成熟的 js-md5 库，与 encryption.md5_encode 结果一致。
export function md5(message: string): string {
  // js-md5 内部处理 UTF-8，直接对字符串取摘要
  return jsMd5(message);
}
