# -*- coding: utf-8 -*-# -*- coding: utf-8 -*-
import json
import re
import pickle
import oauth2
from collections import namedtuple, OrderedDict
from datetime import datetime, timedelta
from functools import wraps
from HTMLParser import HTMLParser


import_ok = True
try:
    import weechat
except ImportError:
    print('This script must be run under WeeChat.')
    print('Get WeeChat now at: http://www.weechat.org/')
    import_ok = False


SCRIPT_NAME = "twitchbot"
SCRIPT_AUTHOR = "frustbox"
SCRIPT_VERSION = "0.1"
SCRIPT_LICENSE = "GPL3"
SCRIPT_DESCRIPTION = "This is an extensible bot for twitch chats."

TWITTER_CONSUMER_KEY = 'XXXXXXXXXXXXXXXXXXXXXXXXX'
TWITTER_CONSUMER_SECRET = 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'
TWITTER_ACCESS_TOKEN = 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'
TWITTER_ACCESS_SECRET = 'XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX'

User = namedtuple('User', ['prefix', 'nick'])
# =====================================
# CONFIG
# =====================================
CHANNELS = {
    'twitch': [
        'frustbox',
        'lorgon',
        ],
}
COMMAND_SYMBOL = '+'

DEBUG = False


def debug(text):
    if DEBUG:
        weechat.prnt("", str(text))


class NotImplemented(Exception):
    pass


# =====================================
# Weechat API Wrappers
# =====================================
class BufferLocalvars(object):
    """Allow accessing localvars as a dict.

    usage:
        localvars = BufferLocalvars(buffer)
        server = localvars['server']
    """
    def __init__(self, buffer):
        self.buffer = buffer

    def __getitem__(self, key):
        return weechat.buffer_get_string(self.buffer, 'localvar_{}'.format(key))

    def __setitem__(self, key, val):
        return weechat.buffer_set(self.buffer, 'localvar_set_{}'.format(key), val)

    def __delitem__(self, key):
        return weechat.buffer_set(self.buffer, 'localvar_set_{}'.format(key), '')

    def __contains__(self, key):
        pass


class BufferNicklist(object):
    """Adapter class for the FUGLY weechat api to get the nicklist.

    usage:
        nicklist = BufferNicklist(buffer)
        for user in nicklist:
            print(user.prefix + user.nick)
    """

    def __init__(self, buffer):
        self.buffer = buffer
        buffer_vars = BufferLocalvars(self.buffer)
        buffer_string = '{server},{channel},'.format(
            server=buffer_vars['server'],
            channel=buffer_vars['channel'],
        )
        self.nicklist = weechat.infolist_get('irc_nick', '', buffer_string)

    def __len__(self):
        return weechat.buffer_get_integer(self.buffer, "nicklist_nicks_count")

    def __iter__(self):
        return self

    def next(self):
        while weechat.infolist_next(self.nicklist):
            name = weechat.infolist_string(self.nicklist, 'name').strip()
            prefix = weechat.infolist_string(self.nicklist, 'prefixes').strip()
            return User(prefix=prefix, nick=name)
        raise StopIteration


def is_valid_nick(nick=None):
    """Return True if the given nick looks like a valid irc nick, False otherwise."""
    if not nick:
        return False

    return weechat.info_get('irc_is_nick', nick) == '1'


# =====================================
# Twitter API
# =====================================
class TwitterTimeline(object):
    def get(self, handle=None, previous_id=None, length=1):
        """Get twitter timeline for the user."""
        if handle is None:
            return False

        url = 'https://api.twitter.com/1.1/statuses/user_timeline.json'
        payload = {
            'screen_name': handle,
            'count': length,
            'trim_user': 'true',
            'include_rts': 'false',
            'exclude_replies': 'true',
        }
        if previous_id is not None:
            payload['since_id'] = previous_id

        response, content = self.request(url, get_params=payload)
        if response.status is 200:
            return json.loads(content)
        else:
            return False

    def request(self, url, http_method='GET', get_params=None, post_body='', http_headers=None):
        """Make the actual request."""
        consumer = oauth2.Consumer(key=TWITTER_CONSUMER_KEY, secret=TWITTER_CONSUMER_SECRET)
        token = oauth2.Token(key=TWITTER_ACCESS_TOKEN, secret=TWITTER_ACCESS_SECRET)
        client = oauth2.Client(consumer, token)
        if get_params is not None:
            url += '?' + '&'.join(k+'='+str(v) for k, v in get_params.iteritems())
        return client.request(url, method=http_method, body=post_body, headers=http_headers)


# =====================================
# Timer object
# =====================================
class Timer(object):
    """Simple Timer object, to measure times and keep split times."""

    def __init__(self, name="timer"):
        """Initialise the timer."""
        self.name = name
        self.running = False
        self.splits = OrderedDict()
        self.start_time = None
        self.stop_time = None

    # =====================================
    # Logic
    # =====================================
    def add(self, seconds=0):
        """Add seconds to the timer by shifting the start time."""
        if seconds != 0:
            delta = timedelta(seconds=seconds)
            self.start_time = self.start_time - delta
            return True

    def adjustsplit(self, name, seconds=0):
        """Make slight adjustments to existing splits."""
        if name not in self.splits.keys():
            return False

        if seconds != 0:
            delta = timedelta(seconds=seconds)
            self.splits[name] += delta

        return True

    def set(self, seconds=0):
        """Set timer to a specific elapsed time (in seconds)."""
        if seconds != 0:
            delta = timedelta(seconds=seconds)
            self.start_time = datetime.now() - delta
            return True

    def start(self):
        """Start the timer."""
        self.start_time = datetime.now()
        self.stop_time = None
        self.running = True
        return True

    def stop(self):
        """Stop the timer."""
        self.stop_time = datetime.now()
        self.running = False
        return True

    def split(self, name):
        """Add a split to a running timer."""
        if not self.running:
            return False

        self.splits[name] = self.elapsed
        return True

    def removesplit(self, name):
        """Remove a split from the timer."""
        if name not in self.splits.keys():
            return False

        self.splits.pop(name)
        return True

    def renamesplit(self, oldname, newname):
        """Rename a split."""
        if oldname not in self.splits.keys():
            return False

        self.splits = OrderedDict((newname if k == oldname else k, v) for k, v in self.splits.items())

    def restart(self):
        """Restart the timer."""
        self.start_time = datetime.now()
        self.splits = OrderedDict()
        self.stop_time = None
        self.running = True
        return True

    def resplit(self, name):
        """Recreate a split."""
        if not self.running:
            return False

        if name not in self.splits.keys():
            return False

        self.splits[name] = self.elapsed
        return True

    # =====================================
    # Information
    # =====================================
    def has_split(self, name):
        return name in self.splits.keys()

    def get_split(self, name):
        return self.splits[name]

    @property
    def elapsed(self):
        """Return the elapsed time on the timer."""
        if self.running:
            return datetime.now() - self.start_time
        elif self.stopped:
            return self.stop_time - self.start_time
        else:
            return False

    @property
    def has_splits(self):
        """Return if there are splits."""
        return len(self.splits) > 0

    @property
    def stopped(self):
        """Return if the timer has been stopped."""
        return self.stop_time is not None

    @property
    def splits_string(self):
        if self.has_splits:
            return ", ".join(['{}: {}'.format(n, t) for n, t in self.splits.items()])
        else:
            return False


# =====================================
# Decorators
# =====================================
def require_owner(func):
    """"""
    @wraps(func)
    def wrap(self, *args, **kwargs):
        if not self.can_use_owner(kwargs['sender']):
            return
        return func(self, *args, **kwargs)
    return wrap


def require_op(func):
    """"""
    @wraps(func)
    def wrap(self, *args, **kwargs):
        if not self.can_use_op(kwargs['sender']):
            return False
        return func(self, *args, **kwargs)
    return wrap


def require_regular(func):
    """"""
    @wraps(func)
    def wrap(self, *args, **kwargs):
        if not self.can_use_regular(kwargs['sender']):
            return False
        return func(self, *args, **kwargs)
    return wrap


# =====================================
# Bot objects
# =====================================
class BaseBot(object):
    """Bot functionality."""

    # Stuff needed for initialisation:
    # --------------------------------
    def __init__(self, *args, **kwargs):
        self.name = kwargs.pop('name')
        if not self.load():
            self.owner = []
            self.ops = []
            self.regulars = []
            self.blacklist = []
            self.muted = False
            self.previous_response = ''
            self.previous_response_time = None
            self.previous_response_time = datetime.now()

    def save(self):
        """Pickle instance variables dict and save it to a file."""
        state = self.__dict__.copy()
        state = self.clean_state(state)
        with open(self.name, 'w') as f:
            pickle.dump(state, f)

    def load(self):
        """Load state from a file and unpickle instance variables."""
        try:
            with open(self.name, 'r+') as f:
                state = pickle.load(f)
                self.__dict__.update(state)
            debug('Successfully loaded state.')
            return True
        except:
            return False

    def clean_state(self, state):
        """Remove some instance variables from state that would not survive loading (if any)."""
        return state

    # Authentication methods
    # --------------------------------
    def get_owner(self):
        """Return the list of owners for the current channel."""
        return getattr(self, 'owner', [])

    def get_ops(self):
        """Return a list of ops for the current channel."""
        return getattr(self, 'ops', [])

    def get_regulars(self):
        """Return a list of regulars for the current channel."""
        return getattr(self, 'regulars', [])

    def get_blacklist(self):
        """Return a list of blacklisted users for the current channel."""
        return getattr(self, 'blacklist', [])

    def can_use_owner(self, user):
        """Return whether or not the user can use owner commands."""
        if isinstance(user, User):
            nick = user.nick
        else:
            nick = user

        return nick in self.get_owner()

    def can_use_op(self, user):
        """Return whether or not the user can use op commands."""
        if isinstance(user, User):
            nick = user.nick
        else:
            nick = user

        return nick in self.get_ops() or self.can_use_owner(user)

    def can_use_regular(self, user):
        """Return whether or not the user can use regular commands."""
        if isinstance(user, User):
            nick = user.nick
        else:
            nick = user

        return nick in self.get_regulars() or self.can_use_op(user)

    def is_blacklisted(self, user):
        """Return whether or not the user is blacklisted and ignored by the bot."""
        if isinstance(user, User):
            nick = user.nick
        else:
            nick = user
        return nick in self.get_blacklist()

    # Helper methods
    # --------------------------------
    def listcommands(self):
        """Return a list of known commands."""
        d = dir(self)
        return [m.replace('command_', '') for m in d if m.startswith('command_')]

    def get_nicklist(self):
        """Return the list of users in chat. Needs to be implemented by subclasses!"""
        raise NotImplemented

    def nick_in_chat(self, nick):
        """Return whether or not the given nick is currently in chat."""
        return nick in self.get_nicklist()

    def get_own_nick(self):
        """Return the username of the bot. Needs to be implemented by subclasses."""
        raise NotImplemented

    # Dispatching
    # --------------------------------
    def dispatch(self, sender, message):
        """Make the bot do something with the message."""

        # ignore blacklisted users.
        if self.is_blacklisted(sender):
            debug('User {} is blacklisted: {}'.format(sender.nick, message))
            return True

        # Split command and arguments
        command, _, message = message.partition(' ')

        # derive method name and call it with given arguments.
        try:
            method = getattr(self, 'command_{}'.format(command))
            method(sender=sender, message=message)
            return True
        # or maybe the command does not exist.
        except AttributeError:
            debug('Command "{}" does not exist.'.format(command))
            return False

    def say(self, sender=None, text=None, force=False):
        """Make the bot say something."""
        if (not self.muted and text != self.previous_response) or force:
            self.previous_response = text
            self.irc_say(text)
            return True

    def irc_say(self, text):
        """This method is a stub and should be implemented by some IRC layer subclass."""
        raise NotImplemented


class WeechatBot(BaseBot):
    """Subclass of BaseBot.

    This is the "IRC" layer that works as an adapter for BaseBot. Some other IRC
    protocol API can beimplemented here."""

    # Initialisation stuff
    # --------------------------------
    def __init__(self, *args, **kwargs):
        """Connect this bot instance to a channel on the network."""
        self.network = kwargs.pop('network', '')
        self.channel = kwargs.pop('channel', '')
        self.buffer = weechat.info_get('irc_buffer', '{},#{}'.format(self.network, self.channel))

        self.setup_callback()

        super(WeechatBot, self).__init__(*args, **kwargs)

    def setup_callback(self):
        # this feels really awkward, see https://weechat.org/scripts/source/pybuffer.py.html/
        self.__name__ = '{}_{}'.format(self.network, self.channel)
        self._callback = callback(self.callback)
        self._pointer = weechat.hook_print(self.buffer, 'irc_privmsg', '', 1, self._callback, '')

    def callback(self, data, buffer, date, tags, displayed, highlight, prefix, message):
        """Receive a message from the IRC client and turn it over to the bot."""
        if not message.startswith(COMMAND_SYMBOL):
            return weechat.WEECHAT_RC_OK

        sender_data = re.match(r'([~@%]?)(.*)', prefix)
        sender = User(
            prefix=sender_data.group(1).strip(),
            nick=sender_data.group(2).strip(),
        )
        self.dispatch(sender, message.strip()[1:])
        return weechat.WEECHAT_RC_OK

    def clean_state(self, state):
        """Remove some instance variables from state, that may not survive loading."""
        state.pop('_callback')
        state.pop('_pointer')
        state.pop('buffer')
        return super(WeechatBot, self).clean_state(state)

    # Dispatching
    # --------------------------------
    def irc_say(self, text):
        """Send a text to the channel."""
        weechat.command(self.buffer, text)

    # Authentication methods
    # --------------------------------
    def get_owner(self):
        """Return the list of owners."""
        owner = [self.get_own_nick()]
        super_owner = super(WeechatBot, self).get_owner()
        return list(set(owner) | set(super_owner))

    def get_ops(self):
        """Get a list of channel members who are ops."""
        super_nicklist = super(WeechatBot, self).get_ops()
        nicklist = [n.nick for n in self.get_nicklist() if '@' in n.prefix]
        nicklist = list(set(super_nicklist) | set(nicklist))

        return nicklist

    # Helper methods
    # --------------------------------
    def get_nicklist(self):
        """Get a list of people in chat."""
        return BufferNicklist(self.buffer)

    def nick_in_chat(self, nick):
        """Return whether or not the given nick is currently in chat."""
        return weechat.nicklist_search_nick(self.buffer, "", nick)

    def get_own_nick(self):
        """Return the username of the bot."""
        return weechat.buffer_get_string(self.buffer, "localvar_nick")


class BaseCommandsBot(object):
    """Some very basic commands. Just enough to make the bot somewhat useful."""

    @require_op
    def command_mute(self, sender=None, message=''):
        """Mute the bot, it will stop talking but still execute things. Ops only."""
        self.muted = True
        self.say(sender=sender, text="I'll shut up.", force=True)
        self.save()
        return True

    @require_op
    def command_unmute(self, sender=None, message=''):
        """Unmute the bot. Ops only."""
        self.muted = False
        self.say(sender=sender, text="I can speak!")
        self.save()
        return True

    def command_ops(self, sender=None, message=''):
        """Return a list of nicks that can use op commands."""
        return self.say(sender=sender, text=str(self.get_ops()))

    @require_owner
    def command_op(self, sender=None, message=''):
        """Add nick to list of ops. Owner only. Syntax: {symbol}op <nick>"""
        if not is_valid_nick(message):
            return self.say(sender=sender, text="That is not a valid nick.")

        if message in self.ops:
            return self.say(sender=sender, text='{} is already op.')

        self.ops.append(message)
        self.say(sender=sender, text="Ok, {} is now op.".format(message))
        self.save()

    @require_owner
    def command_deop(self, sender=None, message=''):
        """Remove nick from list of ops. Owner only. Syntax: {symbol}deop <nick>"""
        if not is_valid_nick(message):
            self.say(sender=sender, text="That is not a valid nick.")

        if message in self.ops:
            self.ops.remove(message)
            self.say(sender=sender, text="Ok, {} is no longer op.".format(message))
            self.save()

    def command_amiop(self, sender=None, message=''):
        """Tells you if you are an op."""
        if self.can_use_op(sender):
            self.say(sender=sender, text="{}, you are an op.".format(sender.nick))
        else:
            self.say(sender=sender, text="Sorry, {}, you are not.".format(sender.nick))

    def command_regulars(self, sender=None, message=''):
        """Print a list of regulars."""
        if not self.can_use_regular(sender.nick):
            return

        self.say(sender=sender, text=str(self.get_regulars()))

    @require_op
    def command_regular(self, sender=None, message=''):
        """Add nick to list of regulars. Ops only. Syntax: {symbol}regular <nick>"""
        if not is_valid_nick(message):
            self.say(sender=sender, text='That is not a valid nick.')

        if message not in self.regulars:
            self.regulars.append(message)
            self.say(sender=sender, text='OK, {} is a regular.'.format(message))
            self.save()

    @require_op
    def command_deregular(self, sender=None, message=''):
        """Remove nick from list of regulars. Ops only. Syntax: {symbol}deregular <nick>"""
        if not is_valid_nick(message):
            self.say(sender=sender, text='That is not a valid nick.')

        if message in self.regulars:
            self.regulars.remove(message)
            self.say(sender=sender, text='OK, {} is no longer a regular.'.format(message))
            self.save()

    def command_amiregular(self, sender=None, message=''):
        """Tells you if you are regulars."""
        if self.can_use_regular(sender):
            self.say(sender=sender, text='{}, you are a regular.'.format(sender.nick))
        else:
            self.say(sender=sender, text='Sorry, {}, you are not a regular.'.format(sender.nick))

    @require_op
    def command_ignore(self, sender=None, message=''):
        """Add a nick to the blacklist, preventing that person from interacting with the bot. Ops only. Syntax: {symbol}ignore <nick>"""
        if not is_valid_nick(message):
            return self.say(sender=sender, text='That is not a valid nick.')

        if message in self.get_owner():
            return self.say(sender=sender, text='I would never do that. {} is my master.'.format(message))

        if self.can_use_op(message):
            return self.say(sender=sender, text='{} is an op.'.format(message))

        if self.can_use_regular(message):
            return self.say(sender=sender, text='{} is a regular.'.format(message))

        if self.is_blacklisted(message):
            self.blacklist.append(message)
            self.save()
            return self.say(sender=sender, text='Ok, I\'ll ignore {}.'.format(message))
        else:
            return self.say(sender=sender, text='{} is already blacklisted.'.format(message))

    @require_op
    def command_unignore(self, sender=None, message=''):
        """Remove a nick from the blacklist, allowing that person to interact with the bot. Ops only. Syntax: {symbol}unignore <nick>"""
        if not is_valid_nick(message):
            return self.say(sender=sender, text='That is not a valid nick.')

        if message in self.blacklist:
            self.blacklist.remove(message)
            self.save()
            return self.say(sender=sender, text='Ok, I\'ll no longer ignore {}.'.format(message))
        else:
            return self.say(sender=sender, text='{} is not blacklisted.'.format(message))

    def command_commands(self, sender=None, message=''):
        """Show a list of known commands."""
        commands = ', '.join(self.listcommands())
        self.say(sender=sender, text='Known commands: {}'.format(commands))

    def command_help(self, sender=None, message=''):
        """Print help for a given command. Syntax: {symbol}help <command>"""
        if message == '':
            message = 'help'

        command, _, message = message.partition(' ')

        if hasattr(self, 'help_'+command):
            return getattr(self, 'help_'+command)(sender=sender, message=message)

        if not hasattr(self, 'command_'+command):
            return self.say(sender=sender, text='Not a valid command or no help available.')

        method = getattr(self, 'command_'+command)
        self.say(sender, method.__doc__.format(symbol=COMMAND_SYMBOL))


class BotTwitchMixin(object):
    """Add twitch specific functionality."""

    def can_use_owner(self, user):
        """Return True if the user can use owner commands."""
        if isinstance(user, User):
            if '~' in user.prefix:
                return True

        return super(BotTwitchMixin, self).can_use_owner(user)

    def can_use_op(self, user):
        """Return True if the user can use op commands."""
        if isinstance(user, User):
            if '@' in user.prefix:
                return True

        return super(BotTwitchMixin, self).can_use_op(user)

    def can_use_regular(self, user):
        """Return True if the user can use regulars commands."""
        if isinstance(user, User):
            if '%' in user.prefix:
                return True

        return super(BotTwitchMixin, self).can_use_regular(user)

    def get_streamer(self):
        """Return name of the streamer (which is the same as the channel)."""
        return self.channel

    def get_owner(self):
        """Streamer is automatically also an owner."""
        super_list = super(BotTwitchMixin, self).get_owner()
        return list(set(super_list) | set([self.get_streamer()]))

    #def get_regulars(self):
    #    """Return a list of regulars, make sure that subscribers are also regulars."""

    def command_chatters(self, sender=None, message=''):
        """Return the number of viewers in chat."""
        self.say(sender=sender, text='There are {} chatters.'.format(len(self.get_nicklist())))

    #def command_viewers(self, sender, args):
    #    """Report the number of viewers of the stream."""


class BotFunMixin(object):
    """Add some simple fun commands to the bot."""
    def __init__(self, *args, **kwargs):
        self.charm = 'ConeDodger240'
        super(BotFunMixin, self).__init__(*args, **kwargs)

    def command_luck(self, sender=None, message=''):
        """Check if the "good luck charm" is in chat."""
        if self.nick_in_chat(self.charm) or sender == self.charm:
            self.say(sender=sender, text='Oh NO! {} is here. Better save regularly. kurtCone'.format(self.charm))
        else:
            self.say(sender=sender, text='Reoice! You\'re safe, the kurtCone has been dodged.')

    @require_op
    def command_setcharm(self, sender=None, message=''):
        """Set a new user as good luck charm. Ops only. Syntax: {symbol}setcharm <nick>"""
        if not is_valid_nick(message):
            return self.say(sender=sender, text='That is not a valid nickname.')

        self.charm = message
        self.say(sender=sender, text='{} is now the "good luck" charm.'.format(message))


class BotTimerMixin(object):
    """Add timer functionality to the bot."""

    def __init__(self, *args, **kwargs):
        self.active_timer = None
        self.timers = OrderedDict()
        super(BotTimerMixin, self).__init__(*args, **kwargs)

    def command_timer(self, sender=None, message=''):
        """Performs timer related actions: new, del, start, stop, restart, split, resplit, delsplit, status, report, list, active, rename, adjust, adjustsplit. Syntax: {symbol}timer [action] ; {symbol}timer without an action is equivalent to {symbol}timer status"""
        if message is '':
            message = 'status'

        command, _, message = message.partition(' ')

        try:
            method = getattr(self, 'timer_{}'.format(command))
        except AttributeError:
            return

        return method(sender=sender, message=message)

    def help_timer(self, sender=None, message=''):
        """Determine which action is being used and display the docstring for the corresponding method."""
        if message == '':
            return self.say(sender, getattr(self, 'command_timer').__doc__.format(symbol=COMMAND_SYMBOL))

        action, _, message = message.partition(' ')

        if hasattr(self, 'timer_'+action):
            return self.say(sender, getattr(self, 'timer_'+action).__doc__.format(symbol=COMMAND_SYMBOL))

        return self.say(sender=sender, text='{} is not a valid action.'.format(action))

    @require_op
    def timer_new(self, sender=None, message=''):
        """Create a timer. Ops only. Syntax: {symbol}timer new [name]"""
        name, _, _ = message.partition(' ')

        if name is '':
            name = datetime.now().strftime('%Y%m%d%H%M')

        if name in self.timers.keys():
            return self.say(sender=sender, text='Timer "{}" already exists.')

        self.active_timer = name
        self.timers[name] = Timer(name=name)
        self.say(sender=sender, text='Timer "{}" has been created.'.format(name))
        self.save()

    @require_op
    def timer_del(self, sender=None, message=''):
        """Remove a timer. Ops only. Syntax: {symbol}timer del <name>"""
        name, _, _ = message.partition(' ')

        if name is '':
            return self.say(
                sender=sender,
                text='Invalid syntax: {symbol}timer del <name>'.format(symbol=COMMAND_SYMBOL)
            )

        if name not in self.timers.keys():
            return self.say(sender=sender, text='There is no timer with the name "{}"'.format(name))

        if name == self.active_timer:
            self.active_timer = None
        self.timers.pop(name, None)
        self.say(sender=sender, text='Timer "{}" has been removed.'.format(name))
        self.save()

    @require_regular
    def timer_start(self, sender=None, message=''):
        """Starts the named timer or the active timer. Regulars only. Syntax: {symbol}timer start [name]"""
        name, _, _ = message.partition(' ')

        if name is '':
            name = self.active_timer

        if name not in self.timers.keys():
            return self.say(sender=sender, text='Timer "{}" does not exist.'.format(name))

        if self.timers[name].running:
            return self.say(sender=sender, text='Timer "{}" is already running.'.format(name))

        self.timers[name].start()
        self.say(sender=sender, text='Timer "{}" has been started.'.format(name))
        self.save()

    @require_regular
    def timer_stop(self, sender=None, message=''):
        """Stops the named timer or the active timer. Regulars only. Syntax: {symbol}timer stop [name]"""
        name, _, _ = message.partition(' ')
        if name is '':
            name = self.active_timer

        if name not in self.timers.keys():
            return self.say(sender=sender, text='Timer "{}" does not exist.'.format(name))

        if not self.timers[name].running:
            return self.say(sender=sender, text='Timer "{}" is not running.'.format(name))

        self.timers[name].stop()
        self.say(sender=sender, text='Timer "{}" has been stopped: {}'.format(name, self.timers[name].elapsed))
        self.save()

    @require_regular
    def timer_restart(self, sender=None, message=''):
        """Restart a named timer or the active timer. Regulars only. Syntax: {symbol}timer restart [name]"""
        name, _, _ = message.partition(' ')
        if name is '':
            name = self.active_timer

        if name not in self.timers.keys():
            return self.say(sender=sender, text='Timer "{}" does not exist.'.format(name))

        if not self.timers[name].running:
            return self.say(sender=sender, text='Timer "{}" is not running.'.format(name))

        self.timers[name].restart()
        self.say(sender=sender, text='Timer "{}" has been restarted.'.format(name))
        self.save()

    @require_regular
    def timer_split(self, sender=None, message=''):
        """Create a split for the named or active timer. Regulars only. Syntax: {symbol}timer split <split name> [timer name]"""
        splitname, _, timername = message.partition(' ')
        if splitname is '':
            return self.say(
                sender=sender,
                text='Invalid syntax: {symbol}timer split <split name> [timer name]'.format(symbol=COMMAND_SYMBOL)
            )

        if timername is '':
            timername = self.active_timer

        if timername not in self.timers.keys():
            return self.say(sender=sender, text='Timer "{}" does not exist.'.format(timername))

        timer = self.timers[timername]
        if not timer.running:
            return self.say(sender=sender, text='Timer "{}" is not running.'.format(timername))

        if splitname in timer.splits.keys():
            return self.say(sender=sender, text='Split "{}" already exists.'.format(splitname))

        timer.split(splitname)
        splittime = timer.splits[splitname]
        self.say(sender=sender, text='Split "{split}" has been created: {time}'.format(split=splitname, time=splittime))
        self.save()

    @require_regular
    def timer_resplit(self, sender=None, message=''):
        """Update a split time for the named or active timer. Regulars only. Syntax: {symbol}timer resplit <split name> [timer name]"""
        splitname, _, timername = message.partition(' ')

        if splitname is '':
            return self.say(
                sender=sender,
                text='Invalid syntax: {symbol}timer split <split name> [timer name]'.format(symbol=COMMAND_SYMBOL)
            )

        if timername is '':
            timername = self.active_timer

        if timername not in self.timers.keys():
            return self.say(sender=sender, text='Timer "{}" does not exist.'.format(timername))

        timer = self.timers[timername]

        if not timer.has_split(splitname):
            return self.say(sender=sender, text='Split "{}" does not exist.'.format(splitname))

        timer.resplit(splitname)
        splittime = timer.get_split(splitname)
        self.say(sender=sender, text='Split "{name}" has been updated: {time}'.format(
            name=splitname,
            time=splittime))
        self.save()

    @require_op
    def timer_delsplit(self, sender=None, message=''):
        """Remove a split from the named or active timer. Ops only. Syntax: {symbol}timer delsplit <split name> [timer name]"""
        splitname, _, timername = message.partition(' ')
        if splitname is '':
            return self.say(
                sender=sender,
                text='Invalid syntax: {symbol}timer delsplit <split name> [timer name]'.format(symbol=COMMAND_SYMBOL)
            )

        if timername is '':
            timername = self.active_timer

        if timername not in self.timers.keys():
            return self.say(sender=sender, text='Timer "{}" does not exist.'.format(timername))

        if not self.timers[timername].has_split(splitname):
            return self.say(sender=sender, text='Split "{}" does not exist.'.format(splitname))

        self.timers[timername].removesplit(splitname)
        self.say(sender=sender, text='Split "{}" has been removed from timer "{}".'.format(splitname, timername))
        self.save()

    def timer_status(self, sender=None, message=''):
        """Give the status of named or active timer. Syntax: {symbol}timer status [name]"""

        name, _, _ = message.partition(' ')

        if name is '':
            name = self.active_timer

        if name is None:
            return self.say(sender=sender, text='No timer is active and no timer name given.')

        if name not in self.timers.keys():
            return self.say(sender=sender, text='Timer "{}" does not exist.'.format(name))

        timer = self.timers[name]

        if timer.running:
            return self.say(sender=sender, text='Timer "{}" is running: {}'.format(name, timer.elapsed))
        elif timer.stopped:
            return self.say(sender=sender, text='Timer "{}" is stopped: {}'.format(name, timer.elapsed))
        else:
            return self.say(sender=sender, text='Timer "{}" has not been started yet.'.format(name))

    def timer_report(self, sender=None, message=''):
        """Print a more detailed report of the named or active timer. Syntax: {symbol}timer report [name]"""

        name, _, _ = message.partition(' ')

        if name is '':
            name = self.active_timer

        if name not in self.timers.keys():
            return self.say(sender=sender, text='Timer "{}" does not exist.'.format(name))

        timer = self.timers[name]
        splits = timer.splits_string

        if timer.running and splits:
            return self.say(sender=sender, text='Timer "{}" running: {} with splits: {}'.format(
                name,
                timer.elapsed,
                timer.splits_string
            ))
        elif timer.running:
            return self.say(sender=sender, text='Timer "{}" running: {} without splits.'.format(
                name,
                timer.elapsed
            ))
        elif timer.stopped and timer.splits_string:
            return self.say(sender=sender, text='Timer "{}" stopped: {} with splits: {}'.format(
                name,
                timer.elapsed,
                timer.splits_string
            ))
        elif timer.stopped:
            return self.say(sender=sender, text='Timer "{}" stopped: {} without splits.'.format(
                name,
                timer.elapsed
            ))
        else:
            return self.say(sender=sender, text='Timer "{}" has not been started yet.'.format(name))

    def timer_list(self, sender=None, message=''):
        """Print a list of all known timers. Syntax: {symbol}timer list"""
        if not self.can_use_regular(sender):
            return

        if len(self.timers) == 0:
            return self.say(sender=sender, text='No timers exist.')

        timer_string = ', '.join(
            k + ('*' if v.running else '') + ('!' if k == self.active_timer else '')
            for k, v in self.timers.iteritems()
        )
        self.say(sender=sender, text='Known timers: {}  (* = running, ! = default)'.format(timer_string))

    @require_op
    def timer_active(self, sender=None, message=''):
        """Set timer by name to active. Ops only. Syntax: {symbol}timer active <name>"""
        name, _, _ = message.partition(' ')

        if name is '':
            name = self.active_timer

        if name not in self.timers.keys():
            return self.say(sender=sender, text='Timer "{}" does not exist.'.format(name))

        self.active_timer = name
        self.say(sender=sender, text='Timer "{}" is now active.'.format(name))
        self.save()

    @require_op
    def timer_rename(self, sender=None, message=''):
        """Rename a timer. Ops only. Syntax {symbol}timer rename <oldname> <newname>"""
        oldname, _, newname = message.partition(' ')

        if oldname is '' or newname is '':
            return self.say(
                sender=sender,
                text='Invalid syntax: {symbol}timer rename <oldname> <newname>'.format(symbol=COMMAND_SYMBOL)
            )

        if oldname not in self.timers.keys():
            return self.say(sender=sender, text='Timer "{}" does not exist.'.format(oldname))
        if newname in self.timers.keys():
            return self.say(sender=sender, text='Timer "{}" already exists.'.format(newname))

        timer = self.timers.pop(oldname)
        self.timers[newname] = timer
        if oldname == self.active_timer:
            self.active_timer = newname
        self.say(sender=sender, text='Timer "{}" has been renamed to "{}"'.format(oldname, newname))
        self.save()

    @require_op
    def timer_adjust(self, sender=None, message=''):
        """Add or remove seconds from the timer to adjust the time. Ops only. Syntax: {symbol}timer adjust <seconds>"""
        seconds, _, timername = message.partition(' ')

        if seconds is '':
            return self.say(
                sender=sender,
                text='Invalid syntax: {symbol}timer adjust <seconds> [timername]'.format(symbol=COMMAND_SYMBOL)
            )

        try:
            seconds = int(seconds)
        except ValueError:
            return self.say(
                sender=sender,
                text='Invalid syntax: {symbol}timer adjust <seconds> [timername]'.format(symbol=COMMAND_SYMBOL)
            )

        if timername is '':
            timername = self.active_timer

        if timername not in self.timers.keys():
            return self.say(sender=sender, text='Timer "{}" does not exist.'.format(timername))

        self.timers[timername].add(seconds)
        self.say(sender=sender, text='Updated Timer "{}" by {} seconds: {}'.format(
            timername,
            seconds,
            self.timers[timername].elapsed
        ))
        self.save()

    @require_op
    def timer_adjustsplit(self, sender=None, message=''):
        """Add or remove some seconds to the split time. Ops only. Syntax: {symbol}timer adjustsplit <seconds> <split name> [timer name]"""
        seconds, _, message = message.partition(' ')
        splitname, _, timername = message.partition(' ')

        if seconds is '' or splitname is '':
            return self.say(
                sender=sender,
                text='Invalid syntax: {symbol}timer adjustsplit <seconds> <name> [timer]'.format(symbol=COMMAND_SYMBOL)
            )

        try:
            seconds = int(seconds)
        except ValueError:
            return self.say(
                sender=sender,
                text='Invalid syntax: {symbol}timer adjustsplit <seconds> <name> [timer]'.format(symbol=COMMAND_SYMBOL)
            )

        if timername is '':
            timername = self.active_timer

        timer = self.timers[timername]

        if timer.has_split(splitname):
            return self.say(sender=sender, text='Split "{}" does not exist in timer "{}".'.format(splitname, timername))

        timer.adjustsplit(splitname, seconds)
        self.say(sender=sender, text='Split "{}" has been updated: {}'.format(splitname, timer.get_split(splitname)))
        self.save()


class BotCustomizableReplyMixin(object):
    """Add custom commands."""

    def __init__(self, *args, **kwargs):
        self.custom_replies = {}
        super(BotCustomizableReplyMixin, self).__init__(*args, **kwargs)

    def listcommands(self):
        super_list = super(BotCustomizableReplyMixin, self).listcommands()
        commands = self.custom_replies.keys()
        return super_list + commands

    def dispatch(self, sender=None, message=''):
        # we extend the dispatch method of BaseBot and do nothing if a command has already been executed.
        if super(BotCustomizableReplyMixin, self).dispatch(sender, message):
            return True

        if message in self.custom_replies.keys():
            reply = self.custom_replies[message]
            self.say(sender=sender, text=reply)
            return True

        return False

    @require_op
    def command_set(self, sender=None, message=''):
        """Define a custom reply message. Ops only. Syntax: {symbol}set <name> <reply>"""
        name, _, text = message.partition(' ')
        if name is '' or text is '':
            return self.say(
                sender=sender,
                text='Invalid syntax: {symbol}set <name> <text>'.format(symbol=COMMAND_SYMBOL)
            )

        if name in self.listcommands() and name not in self.custom_replies.keys():
            return self.say(sender=sender, text='That command already exists.')

        self.custom_replies[name] = text
        self.say(sender=sender, text='Command "{}" has been set to "{}".'.format(name, text))
        self.save()
        return True

    @require_op
    def command_unset(self, sender=None, message=''):
        """Remove a custom reply message. Ops only. Syntax: {symbol}unset <name>"""
        if ' ' in message or message == '':
            return self.say(sender=sender, text='Invalid syntax {symbol}unset <name>'.format(symbol=COMMAND_SYMBOL))

        if message not in self.custom_replies.keys():
            return self.say(
                sender=sender,
                text='Command "{}" does not exist or is not a custom command.'.format(message)
            )

        self.custom_replies.pop(message)
        self.say(sender=sender, text='Command "{}" has been removed.'.format(message))
        self.save()
        return True


class BotCountersMixin(object):
    """Add counters, commands that count how many times they've been called and report the current count."""

    def __init__(self, *args, **kwargs):
        self.counters = {}
        super(BotCountersMixin, self).__init__(*args, **kwargs)

    def listcommands(self):
        super_list = super(BotCountersMixin, self).listcommands()
        commands = self.counters.keys()
        return super_list + commands

    def dispatch(self, sender=None, message=''):
        # extend dispatch() method
        if super(BotCountersMixin, self).dispatch(sender, message):
            return True

        if message in self.counters.keys():
            self.counters[message]['value'] += 1
            value = self.counters[message]['value']
            reply = self.counters[message]['reply']
            self.say(sender=sender, text=reply.format(value))
            self.save()
            return True

        return False

    def command_counter(self, sender=None, message=''):
        """Performs counter related actions. Syntax: {symbol}counter <action> <name>; where possible actions are: list, new, del, set, add, reply. See {symbol}help counter <action>"""

        action, _, message = message.partition(' ')
        if action is '':
            return self.say(
                sender=sender,
                text='Invalid syntax: {symbol}counter <action>'.format(symbol=COMMAND_SYMBOL)
            )

        try:
            method = getattr(self, 'counter_'+action)
        except AttributeError:
            return self.say(sender=sender, text='{} is not a valid action.'.format(action))

        return method(sender=sender, message=message)

    def help_counter(self, sender=None, message=''):
        """Determine the action being used and display the corresponding method's docstring."""
        if message is '':
            return self.say(sender, getattr(self, 'command_counter').__doc__.format(symbol=COMMAND_SYMBOL))

        action, _, _ = message.partition(' ')

        if hasattr(self, 'counter_'+action):
            return self.say(sender, getattr(self, 'counter_'+action).__doc__.format(symbol=COMMAND_SYMBOL))

        return self.say(sender=sender, text='{} is not a valid action.'.format(action))

    @require_op
    def counter_new(self, sender=None, message=''):
        """Create a new counter. Ops only. Syntax: {symbol}counter new <name> [reply]"""
        name, _, reply = message.partition(' ')
        if name is '':
            return self.say(
                sender=sender,
                text='Invalid syntax: {symbol}counter new <name> [reply]'.format(symbol=COMMAND_SYMBOL)
            )

        if name in self.listcommands():
            return self.say(sender=sender, text='This command already exists.')

        if reply is '':
            reply = 'Counter {}: {}'.format(name, '{}')

        self.counters[name] = {
            'value': 0,
            'reply': reply,
        }
        self.say(sender=sender, text='Counter "{}" has been created.'.format(name))
        self.save()

    @require_op
    def counter_del(self, sender=None, message=''):
        """Remove a counter. Ops only. Syntax: {symbol}counter del <name>"""
        name, _, _ = message.partition(' ')
        if name is '':
            return self.say(
                sender=sender,
                text='Invalid syntax: {symbol}counter del <name>'.format(symbol=COMMAND_SYMBOL)
            )

        if name not in self.counters.keys():
            return self.say(sender=sender, text='Counter "{}" does not exist.'.format(name))

        self.counters.pop(name)
        self.say(sender=sender, text='Counter "{}" has been removed.'.format(name))
        self.save()

    def counter_list(self, sender=None, message=''):
        """Show a list of counters. Syntax: {symbol}counter list"""
        return self.say(sender=sender, text='I know these counters: {}'.format(', '.join(self.counters.keys())))

    @require_op
    def counter_set(self, sender=None, message=''):
        """Set a counter to a value. Ops only. Syntax: {symbol}counter <name> <integer>"""
        try:
            name, _, value = message.partition(' ')
            value = int(value)
        except:
            return self.say(
                sender=sender,
                text='Invalid syntax: {symbol}counter set <name> <integer>'.format(symbol=COMMAND_SYMBOL)
            )

        if name not in self.counters.keys():
            return self.say(sender=sender, text='Counter "{}" does not exist.'.format(name))

        self.counters[name]['value'] = max(0, value)
        self.say(sender=sender, text='Counter "{}" is now: {}'.format(name, value))
        self.save()

    @require_op
    def counter_add(self, sender=None, message=''):
        """Add a value to the counter. Ops only. Syntax: {symbol}counter add <name> <integer>"""
        try:
            name, _, value = message.partition(' ')
            value = int(value)
        except:
            return self.say(
                sender=sender,
                text='Invalid syntax: {symbol}counter add <name> <integer>'.format(symbol=COMMAND_SYMBOL)
            )

        if name not in self.counters.keys():
            return self.say(sender=sender, text='Counter "{}" does not exist.'.format(name))

        self.counters[name]['value'] = max(0, self.counters[name]['value'] + value)
        self.say(sender=sender, text='Counter "{}" is now: {}'.format(name, self.counters[name]['value']))
        self.save()

    @require_op
    def counter_reply(self, sender=None, message=''):
        """Change the reply of a counter without changing the value. Ops only. Syntax: {symbol}counter reply <name> <text>"""
        name, _, reply = message.partition(' ')

        if name is '' or reply is '':
            return self.say(
                sender=sender,
                text='Invalid syntax: {symbol}counter reply <name> <text>'.format(symbol=COMMAND_SYMBOL)
            )

        if name not in self.counters.keys():
            return self.say(sender=sender, text='Counter "{}" does not exist.'.format(name))

        self.counters[name]['reply'] = reply
        self.say(sender=sender, text='Counter "{}" has been updated.'.format(name))
        self.save()


class BotTwitterMixin(object):
    """Implement some twitter functionality."""

    def __init__(self, *args, **kwargs):
        self.twitter_handle = None
        self.latest_tweet = {}
        super(BotTwitterMixin, self).__init__(*args, **kwargs)
        self.twitter_timeline = TwitterTimeline()
        self.setup_twitter_callback()

    def setup_twitter_callback(self):
        """Setup the callback for the timer."""
        self._twitter_callback = callback(self.twitter_callback)
        self._twitter_pointer = weechat.hook_timer(60*1000, 60, 0, self._twitter_callback, '')

    def clean_state(self, state):
        """Remove some instance variables from state that would not survive loading."""
        state.pop('twitter_timeline')
        state.pop('_twitter_callback')
        state.pop('_twitter_pointer')
        return super(BotTwitterMixin, self).clean_state(state)

    def twitter_callback(self, data, remaining_calls):
        """This method is called by the automatic hook_timer and ."""
        latest_tweet = self.get_latest_tweet()
        if latest_tweet:
            self.latest_tweet = latest_tweet
            self.save()
            text = ('Twitter update from @{handle}: "{text}" – '
                    'https://twitter.com/{handle}/status/{id}/').format(**latest_tweet)
            self.say(sender=User(prefix='', nick=''), text=text)
        return weechat.WEECHAT_RC_OK

    def get_latest_tweet(self):
        """Get the latest tweet."""
        previous_id = self.latest_tweet.get('id', None)
        timeline = self.twitter_timeline.get(handle=self.twitter_handle, previous_id=previous_id)

        if timeline:
            # do some cleaning up.
            tweet = timeline[0]
            tweet = {
                'handle': self.twitter_handle,
                'id': tweet['id'],
                'text': ' '.join(HTMLParser().unescape(tweet['text']).split()),
            }
            return tweet
        else:
            return False

    @require_regular
    def command_latest(self, sender=None, message=''):
        """Show the latest tweet from the associated twitter handle. Regulars only.
        See also: {symbol}help handle"""
        if self.latest_tweet:
            text = ('Latest tweet by @{handle}: "{text}" – '
                    'https://twitter.com/{handle}/status/{id}/').format(**self.latest_tweet)
            self.say(sender=sender, text=text)
            return True

    @require_op
    def command_handle(self, sender=None, message=''):
        """Set the twitter handle for this channel or show currently set handle. Ops only.
        Syntax: {symbol}handle [twitch username]"""
        if is_valid_nick(message) and message != self.twitter_handle:
            self.twitter_handle = message
            self.latest_tweet = False
            self.save()
        self.say(sender=sender, text='Listening for twitter updates from @{}'.format(self.twitter_handle))
        return True


class Bot(BotTwitterMixin,
          BotCountersMixin,
          BotCustomizableReplyMixin,
          BotTimerMixin,
          BotFunMixin,
          BotTwitchMixin,
          BaseCommandsBot,
          WeechatBot):
    def __init__(self, *args, **kwargs):
        super(self.__class__, self).__init__(*args, **kwargs)


# =====================================
# Initialisation stuff.
# =====================================

# This Method is taken from https://weechat.org/scripts/source/pybuffer.py.html/
def callback(method):
    """This function will take a bound method or function and make it a callback."""
    # try to create a descriptive and unique name.
    func = method.func_name
    try:
        im_self = method.im_self
        try:
            inst = im_self.__name__
        except AttributeError:
            try:
                inst = im_self.name
            except AttributeError:
                raise Exception("Instance %s has no __name__ attribute" % im_self)
        cls = type(im_self).__name__
        name = '_'.join((cls, inst, func))
    except AttributeError:
        # not a bound method
        name = func

    # set our callback
    import __main__
    setattr(__main__, name, method)
    return name


if __name__ == '__main__' and import_ok:
    weechat.register(
        SCRIPT_NAME,
        SCRIPT_AUTHOR,
        SCRIPT_VERSION,
        SCRIPT_LICENSE,
        SCRIPT_DESCRIPTION,
        "",
        "")

    bots = {}

    #  have the bot listen in whitelisted networks and channels.
    for network, channels in CHANNELS.items():
        for channel in channels:
            key = '{network}_{channel}'.format(network=network, channel=channel)
            bots[key] = Bot(name=key, network=network, channel=channel)
