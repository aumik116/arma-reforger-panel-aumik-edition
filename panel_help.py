"""Authenticated, contextual help from the same manuals shipped as PDFs."""
import re
from pathlib import Path
from flask import abort, jsonify, redirect, render_template_string, send_from_directory

MANUALS={'full':'user-manual','staff':'unit-staff-manual','server':'server-management-manual'}
# Manual heading prefixes keep topic mapping stable when titles are edited.
TOPICS={
    'servers':('server','3-'), 'dashboard':('server','5-'), 'console':('server','use-the-console'),
    'startup':('server','startup-and-resources'), 'configuration':('server','6-'), 'network':('server','network-readings'),
    'mods':('server','7-'), 'mods-workshop':('server','add-one-mod-now'),
    'mods-installed':('server','7-'), 'mods-downloaded':('server','find-recently-added-or-unused-looking-mods'),
    'mods-updates':('server','latest-and-pinned-versions'), 'mods-compare':('server','import-export-and-compare'),
    'mods-presets':('server','8-'), 'players':('server','9-'), 'scheduler':('server','10-'),
    'files':('server','files'), 'persistence':('server','persistence'), 'administration':('server','2-'),
    'admin-accounts':('server','2-'), 'admin-maintenance':('server','configuration-backups'),
    'admin-activity':('server','activity-history'), 'admin-notifications':('server','server-notifications'),
    'account':('server','your-account-and-theme'), 'setup':('server','4-'),
    'unit-dashboard':('staff','3-'), 'unit-roster':('staff','4-'), 'unit-structure':('staff','5-'),
    'unit-qualifications':('staff','grant-or-correct-a-qualification'), 'unit-promotions':('staff','review-a-promotion'),
    'unit-events':('staff','create-an-event'), 'unit-attendance':('staff','review-correct-and-finalize'),
    'unit-references':('staff','sops-and-loadouts'), 'unit-awards':('staff','awards'),
    'unit-campaigns':('staff','campaigns'), 'unit-analytics':('staff','analytics'),
    'unit-catalog':('staff','structure-and-catalogs'), 'unit-staff':('staff','staff-access'),
    'unit-customization':('staff','branding'), 'unit-servers':('staff','2-'), 'units':('staff','1-'),
}
HEADINGS=re.compile(r'<h([23])\s+id="([^"]+)"[^>]*>(.*?)</h\1>',re.S)


def install(api):
    docs=Path(api._BASE_DIR)/'docs'
    @api.app.get('/help')
    def help_index():
        return redirect('/help/manual/'+('staff' if api.unit_only_user() else 'server'))

    @api.app.get('/help/manual/<manual>')
    def help_manual(manual):
        if manual not in MANUALS:abort(404)
        content=(docs/(MANUALS[manual]+'.html')).read_text()
        shell=(Path(api._BASE_DIR)/'help.html').read_text()
        return render_template_string(shell,content=content,manual=manual,title={'staff':'Unit staff manual','server':'Server management manual','full':'Full manual'}[manual])

    @api.app.get('/help/pdf/<manual>')
    def help_pdf(manual):
        if manual not in MANUALS:abort(404)
        return send_from_directory(docs,MANUALS[manual]+'.pdf',as_attachment=True)

    @api.app.get('/help/topic/<topic>')
    def help_topic(topic):
        if topic not in TOPICS:abort(404)
        manual,prefix=TOPICS[topic];content=(docs/(MANUALS[manual]+'.html')).read_text()
        headings=list(HEADINGS.finditer(content))
        selected=next((heading for heading in headings if heading[2]==prefix or heading[2].startswith(prefix) and prefix.endswith('-')),None)
        if selected is None:abort(404)
        end=next((heading.start() for heading in headings if heading.start()>selected.start() and int(heading[1])<=int(selected[1])),len(content))
        excerpt=content[selected.start():end]
        excerpt=re.sub(r'href="#([^"]+)"',lambda match:'href="/help/manual/'+manual+'#'+match[1]+'"',excerpt)
        return jsonify(ok=True,title=re.sub('<[^>]*>','',selected[3]),html=excerpt,manual_url='/help/manual/'+manual+'#'+selected[2])
