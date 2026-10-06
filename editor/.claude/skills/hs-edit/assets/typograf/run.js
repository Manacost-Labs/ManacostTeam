#!/usr/bin/env node
"use strict";
/*
 * Запуск Typograf над текстом из stdin. Вход и выход — JSON в UTF-8.
 *
 *   вход:  {"text": "...", "locale": ["ru", "en-US"], "enable": ["ru/dash/main", ...]}
 *   выход: {"text": "...", "version": "7.8.0"}
 *
 * Включаются только перечисленные правила: набор по умолчанию у Typograf шире
 * и меняет смысл («1/2» -> «½», апострофы в названиях карт, раскладка клавиатуры).
 * Неизвестное имя правила — отказ, а не молчаливый пропуск: опечатка в списке
 * иначе выглядела бы как работающая типографика.
 *
 * Коды выхода: 0 — готово, 2 — неверный вход, 3 — неизвестное правило.
 * Сама библиотека лежит рядом (typograf.all.min.js, MIT) и не требует npm install.
 */
const fs = require("fs");
const path = require("path");

const Typograf = require(path.join(__dirname, "typograf.all.min.js"));

function fail(code, message) {
  process.stderr.write(message + "\n");
  process.exit(code);
}

if (process.argv[2] === "--version") {
  process.stdout.write(Typograf.version + "\n");
  process.exit(0);
}

let request;
try {
  request = JSON.parse(fs.readFileSync(0, "utf8"));
} catch (error) {
  fail(2, "неверный вход: " + error.message);
}
if (typeof request.text !== "string" || !Array.isArray(request.enable)) {
  fail(2, "ожидались поля text (строка) и enable (массив имён правил)");
}

const known = new Set(Typograf.getRules().map((rule) => rule.name));
const unknown = request.enable.filter((name) => !known.has(name));
if (unknown.length) {
  fail(3, "неизвестные правила Typograf " + Typograf.version + ": " + unknown.join(", "));
}

const typograf = new Typograf({ locale: request.locale || ["ru", "en-US"] });
typograf.disableRule("*");
for (const name of request.enable) {
  typograf.enableRule(name);
}

process.stdout.write(
  JSON.stringify({ text: typograf.execute(request.text), version: Typograf.version })
);
