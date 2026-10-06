"""Controlled publication styles; raw author HTML still passes the strict validator."""
import html
from html.parser import HTMLParser

class Layout(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.parts=[];self.row=0;self.row_started=False
    def handle_starttag(self,tag,attrs):
        if tag=='table':self.row=0
        if tag=='tr':self.row_started=False
        if tag=='td' and not self.row_started:
            self.row+=1;self.row_started=True
        base={
            'p':'margin:0 0 28px;line-height:1.9;',
            'h3':'margin:44px 0 18px;line-height:1.4;',
            'ul':'margin:0 0 28px;line-height:1.9;',
            'ol':'margin:0 0 28px;line-height:1.9;',
            'figure':'margin:32px auto;width:100%;max-width:620px;',
            'figcaption':'margin:12px 0 0;font-size:13px;line-height:1.7;color:#596579;',
            'table':'width:100%;max-width:620px;border-collapse:collapse;margin:28px 0 36px;',
        }.get(tag)
        if tag=='img':
            width=dict(attrs).get('width','')
            size=width+'px' if width.isdigit() and 100<=int(width)<=1600 else '100%'
            base='display:block;margin:0 auto;width:'+size+';max-width:100%;height:auto;'
        if tag in {'td','th'}:
            color='#dce5ef' if tag=='th' else '#f6f8fb' if self.row%2 else '#ffffff'
            base='background-color:'+color+';padding:12px;text-align:left;vertical-align:top;border-bottom:1px solid #dfe6ed;font-size:14px;line-height:1.7;'
            if tag=='th':base+='font-weight:700;color:#34465a;'
        cleaned=[(k,v) for k,v in attrs if not (k=='style' and base)]
        if base:cleaned.append(('style',base.rstrip(';')))
        self.parts.append('<'+tag+''.join(' '+k+'="'+html.escape(v or '',quote=True)+'"' for k,v in cleaned)+'>')
    def handle_startendtag(self,tag,attrs):self.handle_starttag(tag,attrs)
    def handle_endtag(self,tag):self.parts.append('</'+tag+'>')
    def handle_data(self,data):self.parts.append(data)
    def handle_entityref(self,name):self.parts.append('&'+name+';')
    def handle_charref(self,name):self.parts.append('&#'+name+';')
    def handle_comment(self,data):self.parts.append('<!--'+data+'-->')


def apply_layout(content):
    parser=Layout();parser.feed(content);parser.close()
    return ''.join(parser.parts)
