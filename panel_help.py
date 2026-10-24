"""Authenticated, contextual help from the same manuals shipped as PDFs."""
import re
from pathlib import Path
from flask import abort, jsonify, redirect, render_template_string, send_from_directory

MANUALS={'full':'user-manual','staff':'unit-staff-manual'}
# Manual heading prefixes keep topic mapping stable when titles are edited.
TOPICS={
    'servers':('full','3-'), 'dashboard':('full','5-'), 'console':('full','use-the-console'),
    'startup':('full','startup-and-resources'), 'configuration':('full','6-'), 'network':('full','network-readings'),
    'mods':('full','7-'), 'mods-workshop':('full','add-one-mod-now'),
    'mods-installed':('full','7-'), 'mods-downloaded':('full','find-recently-added-or-unused-looking-mods'),
    'mods-updates':('full','latest-and-pinned-versions'), 'mods-compare':('full','import-export-and-compare'),
    'mods-presets':('full','8-'), 'players':('full','9-'), 'scheduler':('full','10-'),
    'files':('full','files'), 'persistence':('full','persistence'), 'administration':('full','2-'),
    'admin-accounts':('full','2-'), 'admin-maintenance':('full','configuration-backups'),
    'admin-activity':('full','activity-history'), 'admin-notifications':('full','server-notifications'),
    'account':('full','your-account-and-theme'), 'setup':('full','4-'),
    'unit-dashboard':('staff','3-'), 'unit-roster':('staff','4-'), 'unit-structure':('staff','5-'),
    'unit-qualifications':('staff','grant-or-correct-a-qualification'), 'unit-promotions':('staff','review-a-promotion'),
    'unit-events':('staff','create-an-event'), 'unit-attendance':('staff','review-correct-and-finalize'),
    'unit-references':('staff','sops-and-loadouts'), 'unit-awards':('staff','awards'),
    'unit-campaigns':('staff','campaigns'), 'unit-analytics':('staff','analytics'),
    'unit-catalog':('staff','structure-and-catalogs'), 'unit-staff':('staff','staff-access'),
    'unit-customization':('staff','branding'), 'unit-servers':('staff','2-'), 'units':('staff','1-'),
}
HEADINGS=re.compile(r'<h([23]) id="([^"]+)"[^>]*>(.*?)</h\1>',re.S)


def install(api):
    docs=Path(api._BASE_DIR)/'docs'
    @api.app.get('/help')
    def help_index():
        return redirect('/help/manual/'+('staff' if api.unit_only_user() else 'full'))

    @api.app.get('/help/manual/<manual>')
    def help_manual(manual):
        if manual not in MANUALS:abort(404)
        content=(docs/(MANUALS[manual]+'.html')).read_text()
        shell=(Path(api._BASE_DIR)/'help.html').read_text()
        return render_template_string(shell,content=content,manual=manual,title='Unit staff manual' if manual=='staff' else 'User manual')

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
