# -*- coding: utf-8 -*-# -*- coding: utf-8 -*-
import re
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
COMMAND_INITIATION_SYMBOL = u'+'

DEBUG = False


def debug(text):
    if DEBUG:
        weechat.prnt("", text)


# =====================================
# Weechat API Wrappers
# =====================================
class BufferNicklist(object):
    """Adapter class for the FUGLY weechat api to get the nicklist."""
    buffer = ''

    def __init__(self, buffer):
        self.buffer = buffer
        self.nicklist = weechat.infolist_get("nicklist", self.buffer, "")

    def __len__(self):
        return weechat.buffer_get_integer(self.buffer, "nicklist_nicks_count")

    def __iter__(self):
        return self

    def next(self):
        while weechat.infolist_next(self.nicklist):
            nick_type = weechat.infolist_string(self.nicklist, 'type').strip()
            name = weechat.infolist_string(self.nicklist, 'name').strip()
            prefix = weechat.infolist_string(self.nicklist, 'prefix').strip()
            if nick_type == 'nick':
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
    name = None
    running = False
    splits = OrderedDict()
    start_time = None
    stop_time = None

    def __init__(self, name=u"timer"):
        """Initialise the timer."""
        self.name = name

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
class WeechatBot(object):
    """Bot for weechat that can read messages and reply.

    This is the "IRC" layer. Some other class can be dropped in here."""
    network = None
    channel = None
    buffer = None
    muted = False
    owner = None

    # Initialisation stuff
    # --------------------------------
    def __init__(self, *args, **kwargs):
        """Connect this bot instance to a channel on the network."""
        self.network = kwargs.pop('network', '')
        self.channel = kwargs.pop('channel', '')
        self.buffer = weechat.info_get('irc_buffer', '{},#{}'.format(self.network, self.channel))
        self.owner = [self.get_own_nick()]

        # this feels really awkward, see https://weechat.org/scripts/source/pybuffer.py.html/
        self.__name__ = "{}_{}".format(network, channel)
        self._callback = callback(self.callback)
        self._pointer = weechat.hook_print(self.buffer, 'irc_privmsg', '', 1, self._callback, '')

        super(WeechatBot, self).__init__(*args, **kwargs)

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

    # IRC stuff
    # --------------------------------
    def irc_say(self, text):
        """Send a text to the channel."""
        weechat.command(self.buffer, text)

    def get_nicklist(self):
        """Get a list of people in chat."""
        return BufferNicklist(self.buffer)

    def get_ops(self):
        """Get a list of channel members who are ops."""
        super_nicklist = super(WeechatBot, self).get_ops()
        nicklist = [n.nick for n in self.get_nicklist() if '@' in n.prefix]
        nicklist = list(set(super_nicklist) | set(nicklist))

        debug('WeechatBot.get_ops(): {}'.format(str(nicklist)))

        return nicklist

    def nick_in_chat(self, nick):
        return weechat.nicklist_search_nick(self.buffer, "", nick)

    def get_own_nick(self):
        return weechat.buffer_get_string(self.buffer, "localvar_nick")


class BaseBot(object):
    """Bot functionality."""

    ops = []
    regulars = []
    blacklist = []
    muted = False
    previous_response = u''
    commands = {}

    # Stuff needed for initialisation:
    # --------------------------------
    def __init__(self, *args, **kwargs):
        self.muted = self.get_muted()
        self.owner = self.get_owner()
        self.ops = self.get_ops()
        self.regulars = self.get_regulars()
        self.blacklist = self.get_blacklist()
        super(BaseBot, self).__init__(*args, **kwargs)

    def get_owner(self):
        """Return the owner for the current channel."""
        return self.owners

    def get_ops(self):
        """Return a list of ops for the current channel."""
        # TODO: look in database
        debug("BaseBot.get_ops(): {}".format(str(self.ops)))
        return self.ops

    # this line allows get_ops() to overwritten by subclasses and still be accessed internally
    # uses name mangling.
    __get_ops = get_ops

    def get_regulars(self):
        """Return a list of regulars for the current channel."""
        # TODO: look in database
        return self.regulars

    __get_regulars = get_regulars

    def get_blacklist(self):
        """Return a list of blacklisted users for the current channel."""
        # TODO: look in database
        return self.blacklist

    __get_blacklist = get_blacklist

    def get_muted(self):
        """Return whether or not the bot is muted for the current channel."""
        # TODO: look in database
        return False

    # Helper methods
    # --------------------------------
    def can_use_owner(self, user):
        """Return whether or not the user can use owner commands."""
        if isinstance(user, User):
            nick = user.nick
            prefix = user.prefix
        else:
            nick = user
            prefix = ''

        return nick in self.get_owner()

    def can_use_op(self, user):
        """Return whether or not the user can use op commands."""
        if isinstance(user, User):
            nick = user.nick
            prefix = user.prefix
        else:
            nick = user
            prefix = ''

        return '@' in prefix or nick in self.get_ops() or self.can_use_owner(nick)

    def can_use_regular(self, user):
        """Return whether or not the user can use regular commands."""
        if isinstance(user, User):
            nick = user.nick
            prefix = user.prefix
        else:
            nick = user
            prefix = ''

        return '%' in prefix or nick in self.get_regulars() or self.can_use_op(user)

    def is_blacklisted(self, user):
        """Return whether or not the user is blacklisted and ignored by the bot."""
        if isinstance(user, User):
            nick = user.nick
        else:
            nick = user
        return nick in self.get_blacklist()

    def listcommands(self):
        d = dir(self)
        return [m.replace('command_', '') for m in d if m.startswith('command_')]

    # Dispatching
    # --------------------------------
    def dispatch(self, sender, message):
        """Make the bot do something with the message."""

        # ignore blacklisted users.
        if self.is_blacklisted(sender):
            debug('User {} is blacklisted: {}'.format(sender.nick, message))
            return True

        split_message = message.partition(' ')
        command = split_message[0]
        args = split_message[2]

        # derive method name and call it.
        try:
            method = getattr(self, 'command_{}'.format(command))
            method(sender, args)
            return True
        except AttributeError:
            return False

    def say(self, sender, text, force=False):
        """Make the bot say something."""
        if (not self.muted and text != self.previous_response) or force:
            self.previous_response = text
            self.irc_say(text)
            return True

    # Commands
    # --------------------------------
    def command_mute(self, sender, args):
        """Mute the bot, it will stop talking but still execute things. Ops only."""
        if not self.can_use_op(sender):
            return False

        self.muted = True
        return self.say(sender, "I'll shut up.", force=True)

    def command_unmute(self, sender, args):
        """Unmute the bot. Ops only."""
        if not self.can_use_op(sender):
            return False

        self.muted = False
        return self.say(sender, "I can speak!")

    def command_ops(self, sender, args):
        """Return a list of nicks that can use op commands."""
        if sender.nick in self.get_blacklist():
            return False

        return self.say(sender, str(self.get_ops()))

    def command_op(self, sender, nick):
        """Add nick to list of ops. Owner only. Syntax: +op <nick>"""
        if sender.nick not in self.get_owner():
            return

        if not is_valid_nick(nick):
            return self.say(sender, "That is not a valid nick.")

        if nick not in self.ops:
            self.ops.append(nick)
            self.say(sender, "Ok, {} is now op.".format(nick))

    def command_deop(self, sender, nick):
        """Remove nick from list of ops. Owner only. Syntax: +deop <nick>"""
        if sender.nick not in self.get_owner():
            return

        if not is_valid_nick(nick):
            self.say(sender, "That is not a valid nick.")

        if nick in self.ops:
            self.ops.remove(nick)
            self.say(sender, "Ok, {} is no longer op.".format(nick))

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
            self.say(sender, "That is not a valid nick.")

        if nick not in self.regulars:
            self.regulars.append(nick)
            self.say(sender, "OK, {} is a regular.".format(nick))

    def command_deregular(self, sender, nick):
        """Remove nick from list of regulars. Ops only. Syntax: +deregular <nick>"""
        if not self.can_use_op(sender):
            return

        if not is_valid_nick(nick):
            self.say(sender, "That is not a valid nick.")

        if nick in self.regulars:
            self.regulars.remove(nick)
            self.say(sender, "OK, {} is no longer a regular.".format(nick))

    def command_amiregular(self, sender, args):
        """Tells you if you are regulars."""
        if self.can_use_regular(sender):
            self.say(sender, "{}, you are a regular.".format(sender.nick))
        else:
            self.say(sender, "Sorry, {}, you are not a regular.".format(sender.nick))

    def command_ignore(self, sender, nick):
        """Add a nick to the blacklist, preventing that person from interacting with the bot. Ops only. Syntax: +ignore <nick>"""
        if not self.can_use_op(sender):
            return

        if not is_valid_nick(nick):
            self.say(sender, 'That is not a valid nick.')

        if nick not in self.blacklist:
            self.blacklist.append(nick)
            self.say(sender, 'Ok, I\'ll ignore {}.'.format(nick))
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
        else:
            self.say(sender, '{} is not blacklisted.'.format(nick))

    def command_commands(self, sender, args):
        """Show a list of known commands."""

        commands = ', '.join(self.listcommands())
        self.say(sender, 'Known commands: {}'.format(commands))

    def command_help(self, sender, command):
        """Print help for a given command. Syntax: +help <command>"""
        args = None

        if command is None:
            command = 'help'

        if ' ' in command:
            args = command.split(None, 1)
            command = args[0]
            args = args[1]

        if hasattr(self, 'help_'+command):
            return getattr(self, 'help_'+command)(sender, args)

        if not hasattr(self, 'command_'+command):
            return self.say(sender, 'Not a valid command or no help available.')

        method = getattr(self, 'command_'+command)
        self.say(sender, method.__doc__)


class BotTwitchMixin(object):
    """Add twitch specific functionality."""

    def get_streamer(self):
        debug('BotTwitchMixin.get_streamer(): {}'.format(self.channel))
        return self.channel

    def get_owner(self):
        """Streamer is automatically also an owner."""
        super_list = super(BotTwitchMixin, self).get_owner()
        debug('BotTwitchMixin.get_owner(): {}'.format(str(super_list)))
        return list(set(super_list) | set([self.get_streamer()]))

    def get_regulars(self):
        """Return a list of regulars, make sure that subscribers are also regulars."""

    def command_chatters(self, sender, args):
        """Return the number of users in chat."""
        self.say(sender, 'There are {} chatters.'.format(len(self.get_nicklist())))

    #def command_viewers(self, sender, args):
    #    """"""


class BotFunMixin(object):
    """Add some simple fun commands to the bot."""
    charm = 'ConeDodger240'

    def command_luck(self, sender, args):
        """Check if the "good luck charm" is in chat."""
        debug('Checking luck ...')
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

    active_timer = None
    timers = OrderedDict()

    def command_timer(self, sender, args):
        """Performs timer related actions: new, del, start, stop, restart, split, resplit, delsplit, status, report, list, active, rename, adjust, adjustsplit. Syntax: +timer [action] ; +timer without an action is equivalent to +timer status"""
        if args is None:
            args = 'status'

        args = args.split()
        command = args.pop(0)

        try:
            method = getattr(self, 'timer_{}'.format(command))
        except AttributeError:
            debug('Unknown timer-command: {}'.format(command))
            return

        return method(sender, args)

    def help_timer(self, sender, args):
        """"""
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
            return self.say(sender, 'No timers active.')

        keys = []
        for k, t in self.timers.items():
            name = k
            if t.running:
                name += '*'
            if k == self.active_timer:
                name += '!'
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


class BotCustomizableReplyMixin(object):
    """Add custom commands."""
    custom_replies = {}

    def listcommands(self):
        super_list = super(BotCustomizableReplyMixin, self).listcommands()
        commands = self.custom_replies.keys()
        return super_list + commands

    def command_set(self, sender, args):
        """Define a custom reply message. Ops only. Syntax: +set <name> <reply>"""
        if not self.can_use_op(sender):
            return

        try:
            args = args.split(None, 1)
            name = args.pop(0)
            text = args.pop(0)
        except:
            return self.say(sender, 'Invalid syntax: {}set <name> <text>'.format(COMMAND_INITIATION_SYMBOL))

        if name in self.listcommands() and name not in self.custom_replies.keys():
            return self.say(sender, 'That command already exists.')

        self.custom_replies[name] = text
        self.say(sender, 'Command "{}" has been set to "{}".'.format(name, text))
        return True

    def command_unset(self, sender, args):
        """Remove a custom reply message. Ops only. Syntax: +unset <name>"""
        if not self.can_use_op(sender):
            return False

        try:
            args = args.split(None, 1)
            name = args.pop(0)
        except:
            self.say(sender, 'Invalid syntax {}unset <name>'.format(COMMAND_INITIATION_SYMBOL))
            return False

        if name not in self.custom_replies.keys():
            return self.say(sender, 'Command "{}" does not exist or is not a custom command.'.format(name))

        self.custom_replies.pop(name)
        self.say(sender, 'Command "{}" has been removed.'.format(name))
        return True

    def dispatch(self, sender, message):
        # we extend the dispatch method of BaseBot and do nothing if a command has already been executed.
        if super(BotCustomizableReplyMixin, self).dispatch(sender, message):
            return True

        if reply:
            self.say(sender, reply)
            return True

        return False


class BotCountersMixin(object):
    counters = {}

    def listcommands(self):
        super_list = super(BotCountersMixin, self).listcommands()
        commands = self.counters.keys()
        return super_list + commands

    def dispatch(self, sender, message):
        # extend dispatch() method
        if super(BotCountersMixin, self).dispatch(sender, message):
            return True

        name = message[1:]
        if name in self.counters.keys():
            self.counters[name]['value'] += 1
            value = self.counters[name]['value']
            reply = self.counters[name]['reply']
            return self.say(sender, reply.format(value))

        return False

    def command_counter(self, sender, args):
        """Performs counter related actions. Syntax: +counter <action> <name>; where possible actions are: list, new, del, set, add, reply. See +help counter <action>"""

        try:
            args = args.partition(' ')
            action = args[0]
            message = args[2]
        except:
            return self.say(sender, 'Invalid syntax: +counter <action>')

        try:
            method = getattr(self, 'counter_'+action)
        except AttributeError:
            return self.say(sender, '{} is not a valid action.'.format(action))

        return method(sender, message)

    def help_counter(self, sender, args):
        """"""
        if args is None:
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
            m = message.partition(' ')
            name = m[0]
            reply = m[2]
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

    def counter_del(self, sender, message):
        """Remove a counter. Ops only. Syntax: +counter del <name>"""
        if not self.can_use_op(sender):
            return

        try:
            m = message.partition(' ')
            name = m[0]
        except:
            return self.say(sender, 'Invalid syntax: +counter del <name>')

        if name not in self.counters.keys():
            return self.say(sender, 'Counter "{}" does not exist.'.format(name))

        self.counters.pop(name)
        self.say(sender, 'Counter "{}" has been removed.'.format(name))

    def counter_list(self, sender, message):
        """Show a list of counters. Syntax: +counter list"""
        return self.say(sender, 'I know these counters: {}'.format(', '.join(self.counters.keys())))

    def counter_set(self, sender, message):
        """Set a counter to a value. Ops only. Syntax: +counter <name> <integer>"""
        if not self.can_use_op(sender):
            return

        try:
            m = message.partition(' ')
            name = m[0]
            value = int(m[2])
        except:
            return self.say(sender, 'Invalid syntax: +counter set <name> <integer>')

        if name not in self.counters.keys():
            return self.say(sender, 'Counter "{}" does not exist.'.format(name))

        self.counters[name]['value'] = value
        self.say(sender, 'Counter "{}" is now: {}'.format(name, value))

    def counter_add(self, sender, message):
        """Add a value to the counter. Ops only. Syntax: +counter add <name> <integer>"""
        if not self.can_use_op(sender):
            return

        try:
            m = message.partition(' ')
            name = m[0]
            value = int(m[2])
        except:
            return self.say(sender, 'Invalid syntax: +counter add <name> <integer>')

        if name not in self.counters.keys():
            return self.say(sender, 'Counter "{}" does not exist.'.format(name))

        self.counters[name]['value'] += value
        self.say(sender, 'Counter "{}" is now: {}'.format(name, self.counters[name]['value']))

    def counter_reply(self, sender, message):
        """Change the reply of a counter without changing the value. Ops only. Syntax: +counter reply <name> <text>"""
        if not self.can_use_op(sender):
            return

        try:
            m = message.partition(' ')
            name = m[0]
            reply = m[2]
        except IndexError:
            return self.say(sender, 'Invalid syntax: +counter reply <name> <text>')

        if name not in self.counters.keys():
            return self.say(sender, 'Counter "{}" does not exist.'.format(name))

        self.counters[name]['reply'] = reply
        self.say(sender, 'Counter "{}" has been updated.'.format(name))


class Bot(BotCountersMixin, BotCustomizableReplyMixin, BotTimerMixin, BotFunMixin, BotTwitchMixin, WeechatBot, BaseBot):
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
            bots[key] = Bot(network=network, channel=channel)
