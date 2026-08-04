import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';
const wb=await SpreadsheetFile.importXlsx(await FileBlob.load('C:/Users/HSIA/Downloads/抖音大盘2026年上半年销量前100商品（文胸、运动内衣、贴合内衣、光腿神器）.xlsx'));
console.log((await wb.inspect({kind:'computedStyle',sheetId:'贴合内衣',range:'A1:D5',maxChars:8000})).ndjson);
