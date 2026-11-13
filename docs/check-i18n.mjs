/**
 * Standalone i18n contract test for the Jolven landing page.
 * Usage: node docs/check-i18n.mjs
 * No third-party packages required.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("./index.html", import.meta.url), "utf8");
const source = readFileSync(new URL("./app.js", import.meta.url), "utf8");

const headers = [...source.matchAll(/^\s{2}("pt-BR"|en|es):\s*\{/gm)]
  .map(match => ({ language: match[1].replaceAll('"', ""), position: match.index }));
assert.deepEqual(headers.map(item => item.language), ["pt-BR", "en", "es"]);

const dictionaries = {};
for (let index = 0; index < headers.length; index++) {
  const { language, position } = headers[index];
  const next = index + 1 < headers.length ? headers[index + 1].position : source.indexOf("\n};", position);
  assert.ok(next > position, `Unable to find end of ${language} dictionary`);
  const section = source.slice(position, next);
  const matches = [...section.matchAll(/(?:^|[,\n]\s*)([A-Za-z][A-Za-z0-9]*):\s*("(?:[^"\\]|\\.)*")/g)];
  const entries = matches.map(match => [match[1], JSON.parse(match[2])]);
  const keys = entries.map(([key]) => key);
  assert.equal(new Set(keys).size, keys.length, `Duplicate keys in ${language}`);
  dictionaries[language] = Object.fromEntries(entries);
}

const reference = Object.keys(dictionaries["pt-BR"]).sort();
assert.ok(reference.length >= 150, "Unexpectedly small landing translation catalog");
for (const [language, catalog] of Object.entries(dictionaries)) {
  assert.deepEqual(Object.keys(catalog).sort(), reference, `Missing or extra keys in ${language}`);
  for (const [key, value] of Object.entries(catalog)) {
    assert.equal(typeof value, "string", `${language}.${key} must be a string`);
    assert.ok(value.trim(), `${language}.${key} is empty`);
  }
}

const attributeKeys = [...html.matchAll(/data-i18n(?:-alt|-title|-aria-label)?="([^"]+)"/g)]
  .map(match => match[1]);
for (const key of attributeKeys) {
  assert.ok(reference.includes(key), `Missing HTML translation key: ${key}`);
}

// The fallback HTML is pt-BR, so the no-JavaScript experience must also be translated.
const escapeText = value => value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
const defaults = [...html.matchAll(/<([a-z][a-z0-9-]*)\b[^>]*\sdata-i18n="([^"]+)"[^>]*>([^<]*)<\/\1>/g)];
assert.equal(defaults.length, [...html.matchAll(/data-i18n="/g)].length, "Unverified default text nodes");
for (const match of defaults) {
  assert.equal(match[3], escapeText(dictionaries["pt-BR"][match[2]]), `Stale HTML default for ${match[2]}`);
}

for (const language of ["pt-BR", "es"]) {
  const catalog = dictionaries[language];
  for (const key of ["ctaGet", "ctaGithub", "installTitle", "finalButton", "modeDesktopTitle"]) {
    assert.notEqual(catalog[key], dictionaries.en[key], `Untranslated ${language}.${key}`);
  }
  for (const key of ["ctaGet", "ctaGithub", "installTitle", "finalButton"]) {
    assert.doesNotMatch(catalog[key], /Get Jolven|View on GitHub/, `English CTA in ${language}`);
  }
}

for (const key of ["pageTitle", "pageDescription", "heroImageAlt"]) {
  assert.ok(reference.includes(key), `Missing social/SEO key: ${key}`);
}
for (const meta of ["og:title", "og:description", "og:image:alt", "og:locale"]) {
  assert.ok(html.includes(`property="${meta}"`), `Missing meta: ${meta}`);
}
for (const meta of ["twitter:title", "twitter:description", "description"]) {
  assert.ok(html.includes(`name="${meta}"`), `Missing meta: ${meta}`);
}
assert.ok(source.includes('meta[property="og:locale"]'), "Language switch must update Open Graph locale");
assert.ok(source.includes("location.hash.slice(1)"), "Hreflang deep links must be recognized");
assert.ok(source.includes("translations[document.documentElement.lang].copy"), "Copy feedback must follow current language");

console.log(`Landing i18n: ${reference.length} strings x 3 languages, ${attributeKeys.length} HTML references and ${defaults.length} pt-BR defaults validated.`);
