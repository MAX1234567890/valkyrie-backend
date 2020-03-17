#!/usr/bin/env python
#
# Copyright 2020 Max Steinberg
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
import collections
import colorsys
import json
import os
import sys
from functools import wraps
import re
from google.appengine.api import users

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'lib'))
import urllib
import urlparse

import jinja2
import requests
import webapp2
from google.appengine.ext import ndb
from google.appengine.datastore.datastore_query import Cursor
from requests import request
from requests_toolbelt.adapters import appengine

appengine.monkeypatch()

# TODO: move the push_to_db call to before canonicalize

with open(".TOKEN") as f:
    TOKEN = f.read().strip()

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)),
    extensions=['jinja2.ext.autoescape'],
    autoescape=True)


class Data(ndb.Model):
    # Ancestor = table_name
    guild_id = ndb.IntegerProperty(indexed=True)
    args = ndb.PickleProperty()
    when = ndb.DateTimeProperty(auto_now_add=True)


class VerifiedEmail(ndb.Model):
    # Ancestor = guild_id
    email = ndb.StringProperty(indexed=True)


valid_events = """
    message_delete
    bulk_message_delete
    message_edit
    reaction_add
    reaction_remove
    reaction_clear
    guild_channel_update
    guild_channel_pins_update
    guild_integrations_update
    webhooks_update
    member_join
    member_remove
    member_update
    user_update
    guild_role_create
    guild_role_delete
    guild_role_update
    guild_emojis_update
    voice_state_update
    member_ban
    member_unban""".split()

N = len(valid_events)
HSV_tuples = [(x * 1.0 / N, 0.5, 0.5) for x in range(N)]
RGB_tuples = map(lambda x: colorsys.hsv_to_rgb(*x), HSV_tuples)


def rgb_to_hex(rgb):
    return '#%02x%02x%02x' % (rgb[0] * 255, rgb[1] * 255, rgb[2] * 255)


colours = {
    valid_events[e]: rgb_to_hex(RGB_tuples[e]) for e in range(N)
}


def memoize(function):
    memo = {}

    @wraps(function)
    def wrapper(*args):
        try:
            return memo[args]
        except KeyError:
            rv = function(*args)
            memo[args] = rv
            return rv

    return wrapper


@memoize
def fetch_guild_name(id):
    try:
        resp = requests.get(
            'https://discordapp.com/api/guilds/' + str(id),
            headers={
                "Authorization": "Bot NjY4MTcxNTIzMDQzMDk4NjU4.Xm0GVw.WisczhJWl0DLp1R4ImsL2MxSfTw",
                "User-Agent": "curl/7.58.0"
            }
        ).content

        return json.loads(resp)["name"]  # TODO: fix caching if this fails
    except:
        return str(id)


class MainHandler(webapp2.RequestHandler):
    def get(self):
        # TODO: only show servers the user is verified

        query = Data.query()
        values = query.fetch()

        total = len(values)

        guilds = collections.Counter()
        events = collections.Counter()

        for v in values:  # type: Data
            ty = v.key.flat()[1]

            events[ty] += 1
            guilds[v.guild_id] += 1

        most_common_guild = fetch_guild_name(guilds.most_common(1)[0][0])

        template_values = {
            'events': events,
            'int': int,
            'total': float(total),
            'colours': colours,
            'round': round,
            'guilds': len(guilds),
            'most_frequent_guild': most_common_guild,
            'unique_event_counts': len(events)
        }
        template = JINJA_ENVIRONMENT.get_template('html/index.html')
        self.response.write(template.render(template_values))


class LogsHandler(webapp2.RequestHandler):
    def get(self, guild_spec, type_spec):
        cursor = Cursor(urlsafe=self.request.get('cursor'))

        if guild_spec:
            if type_spec:
                query = Data.query(Data.guild_id == int(guild_spec), ancestor=ndb.Key('Data', type_spec))
            else:
                query = Data.query(Data.guild_id == int(guild_spec))
        else:
            if type_spec:
                query = Data.query(ancestor=ndb.Key('Data', type_spec))
            else:
                query = Data.query()

        query = query.order(-Data.when)
        values, next_cursor, more = query.fetch_page(
            20, start_cursor=cursor)

        total = len(values)

        template_values = {
            'events': values,
            'int': int,
            'total': total,
            'name': fetch_guild_name,
            'json': json,
            'unicode': unicode,
            'str': str,
            'more': more,
            'next_cursor': next_cursor
        }
        template = JINJA_ENVIRONMENT.get_template('html/logs.html')
        self.response.write(template.render(template_values))


class DataHandler(webapp2.RequestHandler):
    def post(self):
        if urllib.unquote_plus(self.request.get("__token")).strip() != TOKEN:
            return

        new_obj = Data(
            parent=ndb.Key("Data", self.request.get('table')),
            guild_id=int(self.request.get("guild_id")),
            args=urlparse.parse_qs(self.request.get("args"))
        )
        new_obj.put()


class AddVerifiedEmail(webapp2.RequestHandler):
    def post(self):
        if urllib.unquote_plus(self.request.get("__token")).strip() != TOKEN:
            return

        print(self.request.get("guild_id"))

        new_obj = VerifiedEmail(
            parent=ndb.Key("VerifiedEmail", self.request.get("guild_id")),
            email=urllib.unquote_plus(self.request.get("email"))
        )
        new_obj.put()


app = webapp2.WSGIApplication([
    ('/', MainHandler),
    ('/logs(?:/guild/([0-9]+))?(?:/type/([a-z_]+))?', LogsHandler),
    ('/data', DataHandler),
    ('/data/verify', AddVerifiedEmail)
], debug=True)
