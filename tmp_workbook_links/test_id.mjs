import { Workbook } from '@oai/artifact-tool'; import fs from 'node:fs/promises';
const wb=Workbook.create(); const sh=wb.worksheets.add('T');
sh.getRange('A1:C2').values=[['plain','formula','apostrophe'],['3830024278724706385',null,"'3830024278724706385"]];
sh.getRange('B2').formulas=[['="3830024278724706385"']]; sh.getRange('A1:C2').format.columnWidth=28; sh.getRange('A1:C2').format.numberFormat='@';
console.log(JSON.stringify(sh.getRange('A1:C2').values),JSON.stringify(sh.getRange('A1:C2').formulas)); const b=await wb.render({sheetName:'T',range:'A1:C2',scale:2,format:'png'}); await fs.writeFile('C:/Users/HSIA/Documents/Insight Agent/tmp_workbook_links/idtest.png',new Uint8Array(await b.arrayBuffer()));
