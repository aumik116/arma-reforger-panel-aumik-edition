"""Server-admin moderation through native Reforger commands, never shell commands."""
import re
from flask import g, jsonify, request
import player_query

IDENTITY = r'(?:[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}|\d{17})'


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(IDENTITY, value):
        raise ValueError('Choose a player UUID or 17-digit Steam ID')
    return value


def parse_bans(output):
    rows = []
    for line in output.replace('\x00','').splitlines():
        match = re.fullmatch(r'\s*(\d+)\s*;\s*(' + IDENTITY + r')\s*;\s*(.*?)\s*', line)
        if match: rows.append(dict(id=match[1], identity=match[2], duration=match[3]))
    return rows


def install(api):
    @api.app.get('/api/players/bans')
    def players_bans():
        try:
            page = int(request.args.get('page', 1))
            if not 1 <= page <= 10000: raise ValueError('Invalid ban page')
            output = player_query.admin_command(api, '#ban list ' + str(page))
            rows = parse_bans(output)
            return jsonify(ok=True, bans=rows, page=page, next_page=page+1 if len(rows)==25 else None,
                           output=output[:65536], note='Live game ban list, 25 entries per page. Search filters this page. Reasons are recorded in panel Activity; the game list does not supply them.')
        except (ValueError, OSError, TimeoutError) as exc:
            return jsonify(ok=False, error=str(exc)), 409

    @api.app.post('/api/players/moderate')
    def players_moderate():
        try:
            data = request.get_json()
            action, target = data.get('action'), identity(data.get('identity'))
            reason = data.get('reason', '')
            if not isinstance(reason, str) or len(reason)>120 or any(ord(c)<32 or c in ';"\\' for c in reason):
                raise ValueError('Reason must be up to 120 characters without control characters, quotes, semicolons or backslashes')
            if action == 'kick':
                config = api.read_config().get('rcon') or {}
                settings = api._cfg
                host = settings.get('RCON_HOST') or config.get('address') or '127.0.0.1'
                # Query again: never kick a player whose session slot was reused.
                if not api.get_server_pid(): raise ValueError('Game server is offline')
                if config.get('permission','monitor')!='admin': raise ValueError('Admin RCON permission is required')
                players = player_query.query_players('127.0.0.1' if host=='0.0.0.0' else host,
                    int(settings.get('RCON_PORT') or config.get('port',19999)), settings.get('RCON_PASSWORD') or config.get('password',''))
                player = next((p for p in players if p['identity'].lower()==target.lower()), None)
                if not player or not re.fullmatch(r'\d{1,10}',str(player['id'])):
                    raise ValueError('Player is no longer connected. Refresh the roster.')
                command = '#kick ' + str(player['id'])
            elif action == 'ban':
                duration = data.get('duration',0)
                if type(duration) is not int or not 0<=duration<=31536000:
                    raise ValueError('Choose permanent or up to 365 days in seconds')
                command = f'#ban create {target} {duration}' + (' ' + reason if reason else '')
            elif action == 'unban': command = '#ban remove ' + target
            else: raise ValueError('Choose kick, ban or unban')
            output = player_query.admin_command(api, command)
            g.audit_details = dict(action=action, identity=target, reason=reason)
            if action=='ban': g.audit_details['duration_seconds']=duration
            return jsonify(ok=True, output=output[:65536], message='Command sent to the game server. Refresh the roster or live ban list to verify the result.')
        except (ValueError, OSError, TimeoutError) as exc:
            return jsonify(ok=False, error=str(exc)), 409
