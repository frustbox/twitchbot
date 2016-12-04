# -*- coding: utf-8 -*-# -*- coding: utf-8 -*-
import re
import pickle
from collections import namedtuple, OrderedDict
from datetime import datetime, timedelta

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
COMMAND_INITIATION_SYMBOL = '+'

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

    # =====================================
    # Information
    # =====================================
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
        command, _, args = message.partition(' ')

        # derive method name and call it with given arguments.
        try:
            method = getattr(self, 'command_{}'.format(command))
            method(sender, args)
            return True
        # or maybe the command does not exist.
        except AttributeError:
            debug('Command "{}" does not exist.'.format(command))
            return False

    def say(self, sender, text, force=False):
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
        if not message.startswith(COMMAND_INITIATION_SYMBOL):
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
    def command_mute(self, sender, args):
        """Mute the bot, it will stop talking but still execute things. Ops only."""
        if not self.can_use_op(sender):
            return False

        self.muted = True
        self.say(sender, "I'll shut up.", force=True)
        self.save()
        return True

    def command_unmute(self, sender, args):
        """Unmute the bot. Ops only."""
        if not self.can_use_op(sender):
            return False

        self.muted = False
        self.say(sender, "I can speak!")
        self.save()
        return True

    def command_ops(self, sender, args):
        """Return a list of nicks that can use op commands."""
        if sender.nick in self.get_blacklist():
            return False

        return self.say(sender, str(self.get_ops()))

    def command_op(self, sender, nick):
        """Add nick to list of ops. Owner only. Syntax: +op <nick>"""
        if not self.can_use_owner(sender):
            return

        if not is_valid_nick(nick):
            return self.say(sender, "That is not a valid nick.")

        if nick in self.ops:
            return self.say(sender, '{} is already op.')

        self.ops.append(nick)
        self.say(sender, "Ok, {} is now op.".format(nick))
        self.save()

    def command_deop(self, sender, nick):
        """Remove nick from list of ops. Owner only. Syntax: +deop <nick>"""
        if not self.can_use_owner(sender):
            return

        if not is_valid_nick(nick):
            self.say(sender, "That is not a valid nick.")

        if nick in self.ops:
            self.ops.remove(nick)
            self.say(sender, "Ok, {} is no longer op.".format(nick))
            self.save()

    def command_amiop(self, sender, args):
        """Tells you if you are an op."""
        if self.can_use_op(sender):
            self.say(sender, "{}, you are an op.".format(sender.nick))
        else:
            self.say(sender, "Sorry, {}, you are not.".format(sender.nick))

    def command_regulars(self, sender, args):
        """Print a list of regulars."""
        if not self.can_use_regular(sender.nick):
            return

        self.say(sender, str(self.get_regulars()))

    def command_regular(self, sender, nick):
        """Add nick to list of regulars. Ops only. Syntax: +regular <nick>"""
        if not self.can_use_op(sender):
            return

        if not is_valid_nick(nick):
            self.say(sender, 'That is not a valid nick.')

        if nick not in self.regulars:
            self.regulars.append(nick)
            self.say(sender, 'OK, {} is a regular.'.format(nick))
            self.save()

    def command_deregular(self, sender, nick):
        """Remove nick from list of regulars. Ops only. Syntax: +deregular <nick>"""
        if not self.can_use_op(sender):
            return

        if not is_valid_nick(nick):
            self.say(sender, 'That is not a valid nick.')

        if nick in self.regulars:
            self.regulars.remove(nick)
            self.say(sender, 'OK, {} is no longer a regular.'.format(nick))
            self.save()

    def command_amiregular(self, sender, args):
        """Tells you if you are regulars."""
        if self.can_use_regular(sender):
            self.say(sender, '{}, you are a regular.'.format(sender.nick))
        else:
            self.say(sender, 'Sorry, {}, you are not a regular.'.format(sender.nick))

    def command_ignore(self, sender, nick):
        """Add a nick to the blacklist, preventing that person from interacting with the bot. Ops only. Syntax: +ignore <nick>"""
        if not self.can_use_op(sender):
            return

        if not is_valid_nick(nick):
            self.say(sender, 'That is not a valid nick.')

        if nick not in self.blacklist:
            self.blacklist.append(nick)
            self.say(sender, 'Ok, I\'ll ignore {}.'.format(nick))
            self.save()
        else:
            self.say(sender, '{} is already blacklisted.'.format(nick))

    def command_unignore(self, sender, nick):
        """Remove a nick from the blacklist, allowing that person to interact with the bot. Ops only. Syntax: +unignore <nick>"""
        if not self.can_use_op(sender):
            return

        if not is_valid_nick(nick):
            self.say(sender, 'That is not a valid nick.')

        if nick in self.blacklist:
            self.blacklist.remove(nick)
            self.say(sender, 'Ok, I\'ll no longer ignore {}.'.format(nick))
            self.save()
        else:
            self.say(sender, '{} is not blacklisted.'.format(nick))

    def command_commands(self, sender, args):
        """Show a list of known commands."""

        commands = ', '.join(self.listcommands())
        self.say(sender, 'Known commands: {}'.format(commands))

    def command_help(self, sender, message):
        """Print help for a given command. Syntax: +help <command>"""
        args = None

        if message == '':
            message = 'help'

        command, _, args = message.partition(' ')

        if hasattr(self, 'help_'+command):
            return getattr(self, 'help_'+command)(sender, args)

        if not hasattr(self, 'command_'+command):
            return self.say(sender, 'Not a valid command or no help available.')

        method = getattr(self, 'command_'+command)
        self.say(sender, method.__doc__)


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

    def command_chatters(self, sender, args):
        """Return the number of viewers in chat."""
        self.say(sender, 'There are {} chatters.'.format(len(self.get_nicklist())))

    #def command_viewers(self, sender, args):
    #    """Report the number of viewers of the stream."""


class BotFunMixin(object):
    """Add some simple fun commands to the bot."""
    def __init__(self, *args, **kwargs):
        self.charm = 'ConeDodger240'
        super(BotFunMixin, self).__init__(*args, **kwargs)

    def command_luck(self, sender, args):
        """Check if the "good luck charm" is in chat."""
        if self.nick_in_chat(self.charm) or sender == self.charm:
            self.say(sender, 'Oh NO! {} is here. Better save regularly. kurtCone'.format(self.charm))
        else:
            self.say(sender, 'Reoice! You\'re safe, the kurtCone has been dodged.')

    def command_setcharm(self, sender, args):
        """Set a new user as good luck charm. Ops only. Syntax: +setcharm <nick>"""
        if not self.can_use_op(sender):
            return

        if not is_valid_nick(args):
            return self.say(sender, 'That is not a valid nickname.')

        self.charm = args
        self.say(sender, '{} is now the "good luck" charm.'.format(args))


class BotTimerMixin(object):
    """Add timer functionality to the bot."""

    def __init__(self, *args, **kwargs):
        self.active_timer = None
        self.timers = OrderedDict()
        super(BotTimerMixin, self).__init__(*args, **kwargs)

    def command_timer(self, sender, args):
        """Performs timer related actions: new, del, start, stop, restart, split, resplit, delsplit, status, report, list, active, rename, adjust, adjustsplit. Syntax: +timer [action] ; +timer without an action is equivalent to +timer status"""
        if args is '':
            args = 'status'

        args = args.split()
        command = args.pop(0)

        try:
            method = getattr(self, 'timer_{}'.format(command))
        except AttributeError:
            return

        return method(sender, args)

    def help_timer(self, sender, args):
        """Determine which action is being used and display the docstring for the corresponding method."""
        if args is None:
            return self.say(sender, getattr(self, 'command_timer').__doc__)

        action = args.split()[0]

        if hasattr(self, 'timer_'+action):
            return self.say(sender, getattr(self, 'timer_'+action).__doc__)

        return self.say(sender, '{} is not a valid action.'.format(action))

    def timer_new(self, sender, args):
        """Create a timer. Ops only. Syntax: +timer new [name]"""
        if not self.can_use_op(sender):
            return

        try:
            name = args.pop(0)
        except IndexError:
            name = datetime.now().strftime('%Y%m%d%H%M')

        if name in self.timers.keys():
            return self.say(sender, 'Timer "{}" already exists.')

        self.active_timer = name
        self.timers[name] = Timer(name=name)
        self.say(sender, 'Timer "{}" has been created.'.format(name))
        self.save()

    def timer_del(self, sender, args):
        """Remove a timer. Ops only. Syntax: +timer del <name>"""
        if not self.can_use_op(sender):
            return

        try:
            name = args.pop(0)
        except IndexError:
            return self.say(sender, 'Invalid syntax, must provide a name: +timer del <name>')

        if name not in self.timers.keys():
            return self.say(sender, 'There is no timer with the name "{}"'.format(name))

        if name == self.active_timer:
            self.active_timer = None
        self.timers.pop(name, None)
        self.say(sender, 'Timer "{}" has been removed.'.format(name))
        self.save()

    def timer_start(self, sender, args):
        """Starts the named timer or the active timer. Regulars only. Syntax: +timer start [name]"""
        if not self.can_use_regular(sender):
            return

        try:
            name = args.pop(0)
        except IndexError:
            name = self.active_timer

        if name not in self.timers.keys():
            return self.say(sender, 'Timer "{}" does not exist.'.format(name))

        if self.timers[name].running:
            return self.say(sender, 'Timer "{}" is already running.'.format(name))

        self.timers[name].start()
        self.say(sender, 'Timer "{}" has been started.'.format(name))
        self.save()

    def timer_stop(self, sender, args):
        """Stops the named timer or the active timer. Regulars only. Syntax: +timer stop [name]"""
        if not self.can_use_regular(sender):
            return

        try:
            name = args.pop(0)
        except IndexError:
            name = self.active_timer

        if name not in self.timers.keys():
            return self.say(sender, 'Timer "{}" does not exist.'.format(name))

        if not self.timers[name].running:
            return self.say(sender, 'Timer "{}" is not running.'.format(name))

        self.timers[name].stop()
        self.say(sender, 'Timer "{}" has been stopped: {}'.format(name, self.timers[name].elapsed))
        self.save()

    def timer_restart(self, sender, args):
        """Restart a named timer or the active timer. Regulars only. Syntax: +timer restart [name]"""
        if not self.can_use_regular(sender):
            return

        try:
            name = args.pop(0)
        except IndexError:
            name = self.active_timer

        if name not in self.timers.keys():
            return self.say(sender, 'Timer "{}" does not exist.'.format(name))

        if not self.timers[name].running:
            return self.say(sender, 'Timer "{}" is not running.'.format(name))

        self.timers[name].restart()
        self.say(sender, 'Timer "{}" has been restarted.'.format(name))
        self.save()

    def timer_split(self, sender, args):
        """Create a split for the named or active timer. Regulars only. +timer split <split name> [timer name]"""
        if not self.can_use_regular(sender):
            return

        try:
            splitname = args.pop(0)
        except IndexError:
            return self.say(sender, 'Invalid syntax: {}timer split <split name> [timer name]'.format(COMMAND_INITIATION_SYMBOL))

        try:
            timername = args.pop(0)
        except IndexError:
            timername = self.active_timer

        if timername not in self.timers.keys():
            return self.say(sender, 'Timer "{}" does not exist.'.format(timername))

        timer = self.timers[timername]
        if not timer.running:
            return self.say(sender, 'Timer "{}" is not running.'.format(timername))

        if splitname in timer.splits.keys():
            return self.say(sender, 'Split "{}" already exists.'.format(splitname))

        self.timers[timername].split(splitname)
        self.say(sender, 'Split "{}" has been created: {}'.format(splitname, self.timers[timername].splits[splitname]))
        self.save()

    def timer_resplit(self, sender, args):
        """Update a split time for the named or active timer. Regulars only. Syntax: +timer resplit <split name> [timer name]"""
        if not self.can_use_regular(sender):
            return

        try:
            splitname = args.pop(0)
        except IndexError:
            return self.say(sender, 'Invalid syntax: {}timer split <split name> [timer name]')

        try:
            timername = args.pop(0)
        except IndexError:
            timername = self.active_timer

        if timername not in self.timers.keys():
            return self.say(sender, 'Timer "{}" does not exist.'.format(timername))

        if splitname not in self.timers[timername].splits.keys():
            return self.say(sender, 'Split "{}" does not exist.'.format(splitname))

        self.timers[timername].splits.pop(splitname)
        self.timers[timername].split(splitname)
        self.say(sender, 'Split "{}" has been updated: {}'.format(splitname, self.timers[timername].splits[splitname]))
        self.save()

    def timer_delsplit(self, sender, args):
        """Remove a split from the named or active timer. Ops only. Syntax: +timer delsplit <split name> [timer name]"""
        if not self.can_use_op(sender):
            return

        try:
            splitname = args.pop(0)
        except IndexError:
            return self.say(sender, 'Invalid syntax: {}timer delsplit <split name> [timer name]')

        try:
            timername = args.pop(0)
        except IndexError:
            timername = self.active_timer

        if timername not in self.timers.keys():
            return self.say(sender, 'Timer "{}" does not exist.'.format(timername))

        if splitname not in self.timers[timername].splits.keys():
            return self.say(sender, 'Split "{}" does not exist.'.format(splitname))

        self.timers[timername].splits.pop(splitname)
        self.say(sender, 'Split "{}" has been removed from timer "{}".'.format(splitname, timername))
        self.save()

    def timer_status(self, sender, args):
        """Give the status of named or active timer. Syntax: +timer status [name]"""

        try:
            name = args.pop(0)
        except IndexError:
            name = self.active_timer

        if name is None:
            return self.say(sender, 'No timer is active and no timer name given.')

        if name not in self.timers.keys():
            return self.say(sender, 'Timer "{}" does not exist.'.format(name))

        timer = self.timers[name]

        if timer.running:
            return self.say(sender, 'Timer "{}" is running: {}'.format(name, timer.elapsed))
        elif timer.stopped:
            return self.say(sender, 'Timer "{}" is stopped: {}'.format(name, timer.elapsed))
        else:
            return self.say(sender, 'Timer "{}" has not been started yet.'.format(name))

    def timer_report(self, sender, args):
        """Print a more detailed report of the named or active timer. Syntax: +timer report [name]"""

        try:
            name = args.pop(0)
        except IndexError:
            name = self.active_timer

        if name not in self.timers.keys():
            return self.say(sender, 'Timer "{}" does not exist.'.format(name))

        timer = self.timers[name]
        running = timer.running
        elapsed = timer.elapsed
        stopped = timer.stopped
        splits = timer.splits_string

        if running and splits:
            return self.say(sender, 'Timer "{}" running: {} with splits: {}'.format(name, elapsed, splits))
        elif running:
            return self.say(sender, 'Timer "{}" running: {} without splits.'.format(name, elapsed))
        elif stopped and splits:
            return self.say(sender, 'Timer "{}" stopped: {} with splits: {}'.format(name, elapsed, splits))
        elif stopped:
            return self.say(sender, 'Timer "{}" stopped: {} without splits.'.format(name, elapsed))
        else:
            return self.say(sender, 'Timer "{}" has not been started yet.'.format(name))

    def timer_list(self, sender, args):
        """Print a list of all known timers. Syntax: +timer list"""
        if not self.can_use_regular(sender):
            return

        if len(self.timers) == 0:
            return self.say(sender, 'No timers exist.')

        keys = []
        for k, t in self.timers.items():
            name = k
            if t.running:
                name += ' (running)'
            if k == self.active_timer:
                name += ' (active)'
            keys.append(name)
        timers = ', '.join(keys)
        self.say(sender, 'Known timers: {}'.format(timers))

    def timer_active(self, sender, args):
        """Set timer by name to active. Ops only. Syntax: +timer active <name>"""
        if not self.can_use_op(sender):
            return

        try:
            name = args.pop(0)
        except IndexError:
            name = self.active_timer

        if name not in self.timers.keys():
            return self.say(sender, 'Timer "{}" does not exist.'.format(name))

        self.active_timer = name
        self.say(sender, 'Timer "{}" is now active.'.format())
        self.save()

    def timer_rename(self, sender, args):
        """Rename a timer. Ops only. Syntax +timer rename <oldname> <newname>"""
        if not self.can_use_op(sender):
            return

        try:
            oldname = args.pop(0)
            newname = args.pop(0)
        except IndexError:
            return self.say(sender, 'Invalid syntax: +timer rename <oldname> <newname>')

        if oldname not in self.timers.keys():
            return self.say(sender, 'Timer "{}" does not exist.'.format(oldname))
        if newname in self.timers.keys():
            return self.say(sender, 'Timer "{}" already exists.'.format(newname))

        timer = self.timers.pop(oldname)
        self.timers[newname] = timer
        if oldname == self.active_timer:
            self.active_timer = newname
        self.say(sender, 'Timer "{}" has been renamed to "{}"'.format(oldname, newname))
        self.save()

    def timer_adjust(self, sender, args):
        """Add or remove seconds from the timer to adjust the time. Ops only. Syntax: +timer adjust <seconds>"""
        if not self.can_use_op(sender):
            return

        try:
            seconds = int(float(args.pop(0)))
        except IndexError:
            return self.say(sender, 'Invalid syntax: {}timer adjust <seconds> [timername]')

        try:
            timername = args.pop(0)
        except IndexError:
            timername = self.active_timer

        if timername not in self.timers.keys():
            return self.say(sender, 'Timer "{}" does not exist.'.format(timername))

        self.timers[timername].add(seconds)
        self.say(sender, 'Updated Timer "{}" by {} seconds: {}'.format(
            timername,
            seconds,
            self.timers[timername].elapsed
        ))
        self.save()

    def timer_adjustsplit(self, sender, args):
        """Add or remove some seconds to the split time. Ops only. Syntax: +timer adjustsplit <split name> <seconds> [timer name]"""
        if not self.can_use_op(sender):
            return

        try:
            splitname = args.pop(0)
            seconds = int(float(args.pop(0)))
        except IndexError:
            return self.say(sender, 'Invalid syntax: {}timer adjustsplit <name> <seconds> [timer]'.format(COMMAND_INITIATION_SYMBOL))

        try:
            timername = args.pop(0)
        except IndexError:
            timername = self.active_timer

        if splitname not in self.timers[timername].splits.keys():
            return self.say(sender, 'Split "{}" does not exist in timer "{}".'.format(splitname, timername))

        self.timers[timername].adjustsplit(splitname, seconds)
        self.say(sender, 'Split "{}" has been updated: {}'.format(splitname, self.timers[timername].splits[splitname]))
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

    def command_set(self, sender, message):
        """Define a custom reply message. Ops only. Syntax: +set <name> <reply>"""
        if not self.can_use_op(sender):
            return

        try:
            name, text = message.split(None, 1)
        except:
            return self.say(sender, 'Invalid syntax: {}set <name> <text>'.format(COMMAND_INITIATION_SYMBOL))

        if name in self.listcommands() and name not in self.custom_replies.keys():
            return self.say(sender, 'That command already exists.')

        self.custom_replies[name] = text
        self.say(sender, 'Command "{}" has been set to "{}".'.format(name, text))
        self.save()
        return True

    def command_unset(self, sender, message):
        """Remove a custom reply message. Ops only. Syntax: +unset <name>"""
        if not self.can_use_op(sender):
            return False

        if ' ' in message or message == '':
            return self.say(sender, 'Invalid syntax {}unset <name>'.format(COMMAND_INITIATION_SYMBOL))

        if message not in self.custom_replies.keys():
            return self.say(sender, 'Command "{}" does not exist or is not a custom command.'.format(message))

        self.custom_replies.pop(message)
        self.say(sender, 'Command "{}" has been removed.'.format(message))
        self.save()
        return True

    def dispatch(self, sender, message):
        # we extend the dispatch method of BaseBot and do nothing if a command has already been executed.
        if super(BotCustomizableReplyMixin, self).dispatch(sender, message):
            return True

        if message in self.custom_replies.keys():
            reply = self.custom_replies[message]
            self.say(sender, reply)
            return True

        return False


class BotCountersMixin(object):
    """"""

    def __init__(self, *args, **kwargs):
        self.counters = {}
        super(BotCountersMixin, self).__init__(*args, **kwargs)

    def listcommands(self):
        super_list = super(BotCountersMixin, self).listcommands()
        commands = self.counters.keys()
        return super_list + commands

    def dispatch(self, sender, message):
        # extend dispatch() method
        if super(BotCountersMixin, self).dispatch(sender, message):
            return True

        if message in self.counters.keys():
            self.counters[message]['value'] += 1
            value = self.counters[message]['value']
            reply = self.counters[message]['reply']
            self.say(sender, reply.format(value))
            self.save()
            return True

        return False

    def command_counter(self, sender, args):
        """Performs counter related actions. Syntax: +counter <action> <name>; where possible actions are: list, new, del, set, add, reply. See +help counter <action>"""

        try:
            action, _, message = args.partition(' ')
        except:
            return self.say(sender, 'Invalid syntax: +counter <action>')

        try:
            method = getattr(self, 'counter_'+action)
        except AttributeError:
            return self.say(sender, '{} is not a valid action.'.format(action))

        return method(sender, message)

    def help_counter(self, sender, args):
        """Determine the action being used and display the corresponding method's docstring."""
        if args is '':
            return self.say(sender, getattr(self, 'command_counter').__doc__)

        action = args.split()[0]

        if hasattr(self, 'counter_'+action):
            return self.say(sender, getattr(self, 'counter_'+action).__doc__)

        return self.say(sender, '{} is not a valid action.'.format(action))

    def counter_new(self, sender, message):
        """Create a new counter. Ops only. Syntax: +counter new <name> [reply]"""
        if not self.can_use_op(sender):
            return

        try:
            name, _, reply = message.partition(' ')
        except:
            return self.say(sender, 'Invalid syntax: +counter new <name> [reply]')

        if name in self.listcommands():
            return self.say(sender, 'This command already exists.')

        if not reply:
            reply = 'Counter {}: {}'.format(name, '{}')

        self.counters[name] = {
            'value': 0,
            'reply': reply,
        }
        self.say(sender, 'Counter "{}" has been created.'.format(name))
        self.save()

    def counter_del(self, sender, message):
        """Remove a counter. Ops only. Syntax: +counter del <name>"""
        if not self.can_use_op(sender):
            return

        try:
            name = message.partition(' ')[0]
        except:
            return self.say(sender, 'Invalid syntax: +counter del <name>')

        if name not in self.counters.keys():
            return self.say(sender, 'Counter "{}" does not exist.'.format(name))

        self.counters.pop(name)
        self.say(sender, 'Counter "{}" has been removed.'.format(name))
        self.save()

    def counter_list(self, sender, message):
        """Show a list of counters. Syntax: +counter list"""
        return self.say(sender, 'I know these counters: {}'.format(', '.join(self.counters.keys())))

    def counter_set(self, sender, message):
        """Set a counter to a value. Ops only. Syntax: +counter <name> <integer>"""
        if not self.can_use_op(sender):
            return

        try:
            name, _, value = message.partition(' ')
            value = int(value)
        except:
            return self.say(sender, 'Invalid syntax: +counter set <name> <integer>')

        if name not in self.counters.keys():
            return self.say(sender, 'Counter "{}" does not exist.'.format(name))

        self.counters[name]['value'] = value
        self.say(sender, 'Counter "{}" is now: {}'.format(name, value))
        self.save()

    def counter_add(self, sender, message):
        """Add a value to the counter. Ops only. Syntax: +counter add <name> <integer>"""
        if not self.can_use_op(sender):
            return

        try:
            name, _, value = message.partition(' ')
            value = int(value)
        except:
            return self.say(sender, 'Invalid syntax: +counter add <name> <integer>')

        if name not in self.counters.keys():
            return self.say(sender, 'Counter "{}" does not exist.'.format(name))

        self.counters[name]['value'] += value
        self.say(sender, 'Counter "{}" is now: {}'.format(name, self.counters[name]['value']))
        self.save()

    def counter_reply(self, sender, message):
        """Change the reply of a counter without changing the value. Ops only. Syntax: +counter reply <name> <text>"""
        if not self.can_use_op(sender):
            return

        try:
            name, _, reply = message.partition(' ')
        except IndexError:
            return self.say(sender, 'Invalid syntax: +counter reply <name> <text>')

        if name not in self.counters.keys():
            return self.say(sender, 'Counter "{}" does not exist.'.format(name))

        self.counters[name]['reply'] = reply
        self.say(sender, 'Counter "{}" has been updated.'.format(name))
        self.save()


class Bot(BotCountersMixin,
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
