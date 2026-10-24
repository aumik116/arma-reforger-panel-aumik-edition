import json,subprocess
from pathlib import Path
from xml.sax.saxutils import escape,quoteattr
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,Table,TableStyle,ListFlowable,ListItem
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
root=Path(__file__).resolve().parents[1]/'docs'
font=Path('/usr/share/fonts/truetype/dejavu')
for name,file in [('Body','DejaVuSans.ttf'),('Body-Bold','DejaVuSans-Bold.ttf'),('Body-Italic','DejaVuSans-Oblique.ttf'),('Body-BoldItalic','DejaVuSans-BoldOblique.ttf')]:pdfmetrics.registerFont(TTFont(name,str(font/file)))
pdfmetrics.registerFontFamily('Body',normal='Body',bold='Body-Bold',italic='Body-Italic',boldItalic='Body-BoldItalic')
styles=getSampleStyleSheet()
styles.add(ParagraphStyle(name='Text',fontName='Body',fontSize=9,leading=14,spaceAfter=7,textColor=colors.HexColor('#23333c')))
for level,size in [(1,25),(2,16),(3,11)]:styles.add(ParagraphStyle(name='H'+str(level),parent=styles['Text'],fontName='Body-Bold',fontSize=size,leading=size*1.25,spaceBefore=15 if level>1 else 0,spaceAfter=9,textColor=colors.HexColor('#174c5b'),keepWithNext=True))
styles.add(ParagraphStyle(name='Cell',parent=styles['Text'],fontSize=8,leading=12,spaceAfter=0))
styles.add(ParagraphStyle(name='Edition',parent=styles['Text'],fontSize=8,textColor=colors.HexColor('#677984'),spaceAfter=14))
width=A4[0]-34*mm

def inline(nodes):
    out=''
    for node in nodes:
        kind=node['t'];value=node.get('c')
        if kind=='Str':out+=escape(value)
        elif kind in ('Space','SoftBreak'):out+=' '
        elif kind=='LineBreak':out+='<br/>'
        elif kind in ('Strong','Emph'):out+=('<b>' if kind=='Strong' else '<i>')+inline(value)+('</b>' if kind=='Strong' else '</i>')
        elif kind=='Code':out+='<font face="Courier">'+escape(value[1])+'</font>'
        elif kind=='Link':
            target=value[2][0]
            if target.endswith('operations.md'):target='https://github.com/aumik116/arma-reforger-panel-aumik-edition/blob/main/docs/operations.md'
            elif target.endswith('.md'):target=target[:-3]+'.pdf'
            out+='<link href='+quoteattr(target)+' color="#176a7d">'+inline(value[1])+'</link>'
        elif kind=='Quoted':out+='“'+inline(value[1])+'”'
        elif kind=='Span':out+=inline(value[1])
    return out

def blocks(nodes):
    result=[]
    for node in nodes:
        kind=node['t'];value=node.get('c')
        if kind in ('Para','Plain'):result.append(Paragraph(inline(value),styles['Text']))
        elif kind=='Header':
            level,attr,text=value;p=Paragraph(inline(text),styles['H'+str(min(level,3))]);p.anchor=attr[0];p.heading_level=level-1;p.outline_title=''.join(n.get('c',' ') if n['t']=='Str' else ' ' for n in text);result.append(p)
        elif kind in ('BulletList','OrderedList'):
            items=value if kind=='BulletList' else value[1]
            result.append(ListFlowable([ListItem(blocks(item),leftIndent=0) for item in items],bulletType='bullet' if kind=='BulletList' else '1',start=None if kind=='BulletList' else value[0][0],leftIndent=15,bulletFontName='Body',bulletFontSize=8,spaceAfter=8))
        elif kind=='Table':
            head=value[3][1];body=[row for group in value[4] for row in group[2]+group[3]];foot=value[5][1];rows=head+body+foot
            data=[]
            for row in rows:
                cells=[]
                for cell in row[1]:cells.append([Paragraph(inline(item.get('c',[])),styles['Cell']) for item in cell[4] if item['t'] in ('Plain','Para')])
                data.append(cells)
            count=len(data[0]);colwidths=[width*.30]+[width*.70/(count-1)]*(count-1) if count>1 else [width]
            table=Table(data,colWidths=colwidths,repeatRows=len(head),hAlign='LEFT')
            table.setStyle(TableStyle([('VALIGN',(0,0),(-1,-1),'TOP'),('GRID',(0,0),(-1,-1),.4,colors.HexColor('#ccdbe0')),('BACKGROUND',(0,0),(-1,len(head)-1),colors.HexColor('#e7f0f2')),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]));result.extend([table,Spacer(1,10)])
        elif kind=='BlockQuote':result.extend(blocks(value))
        elif kind=='CodeBlock':result.append(Paragraph(escape(value[1]).replace('\n','<br/>'),styles['Text']))
    return result

class Manual(SimpleDocTemplate):
    def afterFlowable(self,flowable):
        if hasattr(flowable,'anchor'):
            self.canv.bookmarkPage(flowable.anchor)
            if flowable.heading_level<=1:self.canv.addOutlineEntry(flowable.outline_title,flowable.anchor,flowable.heading_level,False)

def footer(canvas,doc):
    canvas.saveState();canvas.setFont('Body',7);canvas.setFillColor(colors.HexColor('#6c7d85'));canvas.drawString(17*mm,12*mm,'FIELDHQ · Staff documentation');canvas.drawRightString(A4[0]-17*mm,12*mm,'Page '+str(doc.page));canvas.restoreState()

for name in ('user-manual','unit-staff-manual'):
    ast=json.loads(subprocess.check_output(['pandoc',str(root/(name+'.md')),'--from=gfm','--to=json']))
    html=subprocess.check_output(['pandoc',str(root/(name+'.md')),'--from=gfm','--to=html5'],text=True)
    html=html.replace('href="user-manual.md"','href="/help/manual/full"').replace('href="unit-staff-manual.md"','href="/help/manual/staff"').replace('href="operations.md"','href="https://github.com/aumik116/arma-reforger-panel-aumik-edition/blob/main/docs/operations.md"')
    (root/(name+'.html')).write_text(html)
    title='FIELDHQ Unit Staff Manual' if name=='unit-staff-manual' else 'FIELDHQ User Manual'
    doc=Manual(str(root/(name+'.pdf')),pagesize=A4,leftMargin=17*mm,rightMargin=17*mm,topMargin=18*mm,bottomMargin=20*mm,title=title,author='FIELDHQ',allowSplitting=True)
    doc.build([Paragraph('FIELDHQ · Edition 24 October 2026',styles['Edition'])]+blocks(ast['blocks']),onFirstPage=footer,onLaterPages=footer)
    print(name+'.pdf')
