import json,subprocess,re
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

# Reuse the hosting chapters so fixes also reach the focused server manual.
full=(root/'user-manual.md').read_text()
chapters=re.split(r'(?=^## \d+\. )',full,flags=re.M)[1:]
selected=[]
for chapter in chapters:
    number=int(re.match(r'## (\d+)',chapter)[1])
    if number not in tuple(range(1,12))+(18,19):continue
    if number==2:
        chapter=chapter.split('### Unit staff')[0]+'For unit roles and personnel workflows, see the [unit staff manual](unit-staff-manual.md).\n\n'
    if number==18:chapter=chapter.replace('## 18.','## 12.',1)
    if number==19:
        chapter=chapter.replace('## 19.','## 13.',1).replace('4. Stop the server','1. Stop the server')
        chapter=chapter.replace('1. Select the correct server and unit.','1. Select the correct server.')
        chapter=re.sub(r'^\d+\. .*?(?:unit event|UUIDs linked|event evidence|finalize attendance|member notes).*?\n','',chapter,flags=re.M|re.I)
    selected.append(chapter)
body=''.join(selected)
body=re.sub(r'^\| Save a roster record, note or reference.*?\n','',body,flags=re.M)
body=re.sub(r'^- \*\*Unit role and permissions:.*?\n','',body,flags=re.M)
body=body.replace('current server tab or unit page','current server tab').replace('both full manuals','all three manuals').replace('server/unit name','server name')
body=body.replace('Unit staff use the same login page as hosting staff.','').replace('There are separate layers of access:','Server access has these layers:')

body=body.replace('Only units and servers available to your account appear. A unit-only staff account may have no hosting workspace to open. A roster member does not need a panel account.','Only servers available to your account appear. Ask a panel administrator if an expected server is missing.')
body=body.replace('Choose **Hosting** for servers or **Units** / **Units & rosters** for unit work.','Choose **Hosting** for server management.')
body=re.sub(r'^5\. In Units,.*?\n','',body,flags=re.M)
body=re.sub(r'^\| A unit, server or action is missing.*?\n','| A server or action is missing | Ask a panel administrator to check direct server access and your role. |\n',body,flags=re.M)
body=re.sub(r'^\| (?:Member has|Attendance did).*?\n','',body,flags=re.M)
headings=re.findall(r'^## (.+)$',body,re.M)
toc='\n'.join(f'{index}. [{heading.split(". ",1)[1]}](#'+re.sub(r'[^a-z0-9 -]','',heading.lower()).replace(' ','-')+')' for index,heading in enumerate(headings,1))
(root/'server-management-manual.md').write_text('# FIELDHQ server management manual\n\nFor hosting staff managing Arma Reforger servers. For personnel workflows, use the [unit staff manual](unit-staff-manual.md); the [full manual](user-manual.md) covers both.\n\n## Contents\n\n'+toc+'\n\n'+body)

for name in ('user-manual','unit-staff-manual','server-management-manual'):
    ast=json.loads(subprocess.check_output(['pandoc',str(root/(name+'.md')),'--from=gfm','--to=json']))
    html=subprocess.check_output(['pandoc',str(root/(name+'.md')),'--from=gfm','--to=html5'],text=True)
    html=html.replace('href="user-manual.md"','href="/help/manual/full"').replace('href="unit-staff-manual.md"','href="/help/manual/staff"').replace('href="server-management-manual.md"','href="/help/manual/server"').replace('href="operations.md"','href="https://github.com/aumik116/arma-reforger-panel-aumik-edition/blob/main/docs/operations.md"')
    (root/(name+'.html')).write_text(html)
    title={'user-manual':'FIELDHQ Full User Manual','unit-staff-manual':'FIELDHQ Unit Staff Manual','server-management-manual':'FIELDHQ Server Management Manual'}[name]
    doc=Manual(str(root/(name+'.pdf')),pagesize=A4,leftMargin=17*mm,rightMargin=17*mm,topMargin=18*mm,bottomMargin=20*mm,title=title,author='FIELDHQ',allowSplitting=True)
    doc.build([Paragraph('FIELDHQ · Edition 24 October 2026',styles['Edition'])]+blocks(ast['blocks']),onFirstPage=footer,onLaterPages=footer)
    print(name+'.pdf')
