# -*- coding: utf-8 -*-# -*- coding: utf-8 -*-
import time
import re
from collections import namedtuple
from datetime import datetime, timedelta

import_ok = True
try:
    import weechat
except ImportError:
    print('This script must be run under WeeChat.')
    print('Get WeeChat now at: http://www.weechat.org/')
    import_ok = False


SCRIPT_NAME = "weechat_twitchbot"
SCRIPT_AUTHOR = "frustbox"
SCRIPT_VERSION = "0.1"
SCRIPT_LICENSE = "GPLv3"
SCRIPT_DESCRIPTION = "This is an extensible bot for twitch chats."


# =====================================
# CONFIG
# =====================================
CHANNELS = {
    'twitch': [
        'frustbox',
        'lorgon',
        ],
}
OWNER = 'frustbox'

DEBUG = False
OK = weechat.WEECHAT_RC_OK  # tired of typing this all the time


# =====================================
# Timer object
# =====================================
class Timer(object):
    """Simple Timer object, to measure times and keep split times."""
    name = None
    running = False
    splits = []
    start_time = None
    stop_time = None

    def __init__(self, name=u"timer"):
        """Initialise the timer."""
        self.name = name

    # =====================================
    # Logic
    # =====================================
    def start(self):
        """Start the timer."""
        self.start_time = datetime.now()
        self.splits = []
        self.stop_time = None
        self.running = True
        return True

    def restart(self):
        """Restart the timer."""
        self.start_time = datetime.now()
        self.splits = []
        self.stop_time = None
        self.running = True
        return True

    def stop(self):
        """Stop the timer."""
        self.stop_time = datetime.now()
        self.running = False
        return True

    def add(self, seconds=0):
        """Add seconds to the timer by shifting the start time."""
        if seconds != 0:
            delta = timedelta(seconds=seconds)
            self.start_time = self.start_time - delta
            return True

    def set(self, seconds=0):
        """Set timer to a specific elapsed time (in seconds)."""
        if seconds != 0:
            delta = timedelta(seconds=seconds)
            self.start_time = datetime.now() - delta
            return True

    def split(self, name):
        """Add a split to a running timer."""
        if self.running:
            Split = namedtuple('Split', ['name', 'time'])
            this_split = Split(name=name, time=self.elapsed)
            self.splits.append(this_split)
            return this_split
        else:
            return False

    # =====================================
    # Information
    # =====================================
    @property
    def elapsed(self):
        """Return the elapsed time on the timer."""
        if self.running:
            return datetime.now() - self.start_time
        else:
            return self.stop_time - self.start_time


# =====================================
# Bot objects
# =====================================
class WeechatBot(object):
    """Bot for weechat that can read messages and reply.

    This is the IRC layer. Some other class can be dropped in here."""
    network = None
    channel = None
    buffer = None
    muted = False
    owner = None

    def __init__(self, network, channel):
        """Connect to a network and channel"""
        self.network = network
        self.channel = channel
        self.buffer = weechat.info_get('irc_buffer', '{},#{}'.format(network, channel))
        self.owner = OWNER
        weechat.hook_print(self.buffer, 'irc_privmsg', '', 1, self.callback, '')
        super(self.__class__, self).__init__(network, channel)

    def callback(self, sender, message):
        """This is the callback method called by weechat."""
        self.dispatch(sender, message)
        return OK

    def say(self, message=None, force=False):
        """Speak, bot, speak!"""

        if self.muted and not force:
            return True

        weechat.command(self.buffer, message)

    def is_valid_nick(self, nick):
        """Return true if `nick` is a valid irc nick."""

    def nick_in_chat(self, nick):
        return True

    def is_op(self, nick):
        """"""

    def get_nicklist(self):
        """Return the list of chatters."""


class BotTwitchMixin(object):
    def stream_is_live(self):
        """Return whether or not the stream is live."""

    def get_stream_title(self):
        """Return the title for the current stream."""

    def get_viewers(self):
        """Return the number of viewers."""

    def is_subscriber(self, nick):
        """Return True if `nick` is a subscriber to the channel."""

    def get_uptime(self, nick):
        """Return how long the stream has been going."""


class BotTimerMixin(object):
    """Bot functionality that implements timers."""
    timer = Timer()

    def dispatch_op_commands(self, sender, message):
        """"""
    def dispatch_regular_commands(self, sender, message):
        """"""


class BotCounterMixin(object):
    """Keeps count how many times a command was used."""
    counters = {}

    def dispatch_everybody_commands(self, sender, message):
        """"""

    def dispatch_regular_commands(self, sender, message):
        """"""

    def dispatch_op_commands(self, sender, message):
        """"""


class BotFunMixin(object):
    """Some fun commands."""

    def dispatch_regular_commands(self, sender, message):
        """"""

    def dispatch_everybody_commands(self, sender, message):
        """"""

    def command_info(self, sender):
        return self.say(u'')

    def command_luck(self, sender):
        """Check if conedodger240 is in the viewer list and reply."""
        if sender == 'conedodger240' or self.nick_in_chat('conedodger240'):
            self.say(sender, u'Oh NO! ConeDodger240 is here. kurtCone')
        else:
            self.say(sender, u'Rejoice! You\'re safe, the kurtCone has been dodged.')


class Bot(WeechatBot, BotTwitchMixin, BotTimerMixin, BotFunMixin):
    """Bot functionality."""

    ops = []
    regulars = []
    blacklist = []

    def __init__(self, network, channel):
        super(self.__class__, self).__init__(network, channel)

    def is_command(self, message):
        return message.startswith(u'+')

    def is_streamer(self, nick):
        return nick == self.channel

    def is_owner(self, nick):
        return nick == self.owner or self.is_streamer(nick)

    def is_op(self, nick):
        return nick in self.ops

    def is_regular(self, nick):
        return nick in self.regulars

    def is_blacklisted(self, nick):
        return nick in self.blacklist

    def can_use_regular(self, nick):
        return self.is_owner(nick) or self.is_op(nick) or self.is_owner(nick)

    def can_use_op(self, nick):
        return self.is_owner(nick) or self.is_op(nick)

    def dispatch(self, sender, message):
        """Make the bot do something."""

        if not self.is_command(message):
            return

        if self.is_blacklisted(sender):
            return

        if self.is_owner(sender):
            self.dispatch_owner_commands(sender, message)

        if self.can_use_op(sender):
            self.dispatch_op_commands(sender, message)

        if self.can_use_regular(sender):
            self.dispatch_regular_commands(sender, message)

        self.dispatch_everybody_commands(sender, message)

    def dispatch_owner_commands(self, sender, message):
        """Commands to be used by the owner."""
        super(self.__class__, self).dispatch_owner_commands(sender, message)

    def dispatch_op_commands(self, sender, message):
        """Commands to be used by ops."""
        super(self.__class__, self).dispatch_op_commands(sender, message)

    def dispatch_regular_commands(self, sender, message):
        """Commands to be used by regulars."""
        super(self.__class__, self).dispatch_regular_commands(sender, message)

    def dispatch_everybody_commands(self, sender, message):
        """Commands that can be used by everybody. (Beware of spam!)"""
        super(self.__class__, self).dispatch_everybody_commands(sender, message)


if __name__ == '__main__' and import_ok:
    weechat.register(
        SCRIPT_NAME,
        SCRIPT_AUTHOR,
        SCRIPT_VERSION,
        SCRIPT_LICENSE,
        SCRIPT_DESCRIPTION,
        "",
        "")
    weechat.prnt("", str(CHANNELS))

    #  have the bot listen in whitelisted networks and channels.
    bots = {}
    for network, channels in CHANNELS.items():
        for channel in channels:
            key = '{network}_{channel}'.format(network=network, channel=channel)
            bots[key] = Bot(network=network, channel=channel)
