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
# Timer stuff.
# =====================================
my_timer = Timer()


def timer_start(buffer, nick):
    """Start the timer."""
    global my_timer

    if my_timer and not my_timer.running:
        my_timer.start()
        return bot_say(buffer, nick, u'Timer started.')


def timer_restart(buffer, nick):
    """Restart the timer."""
    global my_timer

    if my_timer and my_timer.running:
        my_timer.restart()
        return bot_say(buffer, nick, u'Timer restarted: {}'.format(my_timer.elapsed))


def timer_add(buffer, nick, seconds):
    """Add seconds to the timer."""
    global my_timer

    seconds = int(float(seconds))

    if my_timer and my_timer.running:
        my_timer.add(seconds)
        return bot_say(buffer, nick, u'Added {} seconds to the timer: {}'.format(
            seconds,
            my_timer.elapsed,
        ))


def timer_stop(buffer, nick):
    """Stop the timer."""
    global my_timer

    if my_timer and my_timer.running:
        my_timer.stop()
        return bot_say(buffer, nick, u'Timer stopped after {}'.format(my_timer.elapsed))


def timer_split(buffer, nick, name):
    """Add a split time to the timer."""
    global my_timer

    if my_timer and my_timer.running:
        split = my_timer.split(name)
        if split:
            return bot_say(buffer, nick, u'Split "{}" created: {}'.format(split.name, split.time))

    else:
        return bot_say(buffer, nick, u'Timer must be running.')


def timer_status(buffer, nick):
    """Print the status of the timer."""
    global my_timer

    if my_timer and my_timer.running:
        return bot_say(buffer, nick, u'Timer running: {}'.format(my_timer.elapsed))
    elif my_timer.stop_time:
        return bot_say(buffer, nick, u'Timer stopped: {}'.format(my_timer.elapsed))
    else:
        return bot_say(buffer, nick, u'Timer not running')


def timer_report(buffer, nick):
    """Print a full report with all splits."""
    global my_timer

    if my_timer:
        splits = ", ".join(['{}: {}'.format(n, t) for n, t in my_timer.splits])
        if my_timer.running and splits != '':
            return bot_say(buffer, nick, u'Timer running: {}, with splits: {}'.format(
                my_timer.elapsed,
                splits
            ))
        elif my_timer.running:
            return bot_say(buffer, nick, u'Timer running: {}, with no splits'.format(
                my_timer.elapsed,
            ))
        elif my_timer.stop_time and splits:
            return bot_say(buffer, nick, u'Timer stopped: {}, with splits: {}'.format(
                my_timer.elapsed,
                splits
            ))
        elif my_timer.stop_time:
            return bot_say(buffer, nick, u'Timer stopped: {}, with no splits'.format(
                my_timer.elapsed,
            ))
        else:
            return bot_say(buffer, nick, u'Whoops.')


# =====================================
# Just for Fun commands
# =====================================
def cone(buffer, nick):
    """Check if conedodger240 is in the viewer list and reply."""
    if DEBUG:
        weechat.prnt("", 'DEBUG: luck')
    if weechat.nicklist_search_nick(buffer, "", "conedodger240") or nick == 'conedodger240':
        return bot_say(buffer, nick, u'Oh NO! ConeDodger240 is here. kurtCone')
    else:
        return bot_say(buffer, nick, u'Rejoice! You\'re safe, the kurtCone has been dodged.')

# =====================================
# Bot control
# =====================================
OWNER = 'frustbox'
USERS_OP = ['mateuszdrwal', 'lorgon']
USERS_REGULAR = ['bobbyann', 'edi_j', 'marcmagus', 'mbxdllfs', 'docgratis', 'conedodger240']
USERS_BLACKLIST = []
WHITELISTED_NETWORKS = ['twitch']
WHITELISTED_CHANNELS = ['#lorgon', '#frustbox']
MUTED_BUFFERS = []


# OWNER commands
def bot_op(buffer, nick, name):
    """Add user to OP list."""
    name = name.strip().lower()
    if not weechat.info_get('irc_is_nick', name):
        return bot_say(buffer, nick, u'That is not a valid username.')

    if name == OWNER:
        return bot_say(buffer, nick, u'{} is my owner.'.format(name))

    if name in USERS_OP:
        return bot_say(buffer, nick, u'{} is already OP'.format(name))

    if name in USERS_REGULAR:
        USERS_REGULAR.remove(name)

    USERS_OP.append(name)
    return bot_say(buffer, nick, u'{} is now a regular.'.format(name))


def bot_deop(buffer, nick, name):
    """Remove user from OP list."""
    name = name.strip().lower()
    if not weechat.info_get('irc_is_nick', name):
        return bot_say(buffer, nick, u'That is not a valid username.')

    if name == OWNER:
        return bot_say(buffer, nick, u'{} is my owner.'.format(name))

    if name not in USERS_OP:
        return bot_say(buffer, nick, u'{} is not an OP'.format(name))

    if name in USERS_OP:
        USERS_OP.remove(name)
        return bot_say(buffer, nick, u'{} is no longer an OP'.format(name))


def bot_regular(buffer, nick, name):
    """Add user to regulars list."""
    global USERS_REGULAR

    name = name.strip().lower()
    if not weechat.info_get('irc_is_nick', name):
        return bot_say(buffer, nick, u'That is not a valid username.')

    if name == OWNER:
        return bot_say(buffer, nick, u'{} is my owner.'.format(name))

    if name in USERS_OP:
        return bot_say(buffer, nick, u'{} is already OP'.format(name))

    if name in USERS_REGULAR:
        return bot_say(buffer, nick, u'{} is already a regular'.format(name))

    USERS_REGULAR.append(name)
    return bot_say(buffer, nick, u'{} is now a regular.'.format(name))


def bot_deregular(buffer, nick, name):
    """Remove a user from regulars list."""
    global USERS_REGULAR

    name = name.strip().lower()
    if not weechat.info_get('irc_is_nick', name):
        return bot_say(buffer, nick, u'That is not a valid username')

    if name not in USERS_REGULAR:
        return bot_say(buffer, nick, u'{} is not a regular.'.forman(name))

    USERS_REGULAR.remove(name)
    return bot_say(buffer, nick, u'{} is no longer a regular.'.format(name))


def bot_mute(buffer, nick):
    """Add buffer to muted buffers list."""
    global MUTED_BUFFERS
    if buffer not in MUTED_BUFFERS:
        MUTED_BUFFERS.append(buffer)
        return bot_say(buffer, nick, u'I\'ll shut up.', True)


def bot_unmute(buffer, nick):
    """Remove buffer from muted buffers list."""
    global MUTED_BUFFERS
    if buffer in MUTED_BUFFERS:
        MUTED_BUFFERS.remove(buffer)
        return bot_say(buffer, nick, u'I can speak again.')


# =====================================
# Weechat stuff
# =====================================
def bot_say(buffer, nick, text, force=False):
    """Make the bot say someting in `buffer`."""
    if DEBUG:
        weechat.prnt("", "DEBUG: bot_say -- {}".format(text))

    if buffer in MUTED_BUFFERS and not force:
        return OK

    if nick == "frustbox":
        time.sleep(0.25)

    weechat.command(buffer, text)
    return OK


def bot_dispatch(buffer, nick, message):
    """Make the bot do something."""
    if DEBUG:
        weechat.prnt("", "DEBUG: bot_dispatch -- {}".format(message))

    # ===================
    # Everybody commands:
    # ===================
    if message == '+lifefruit':
        return bot_say(buffer, nick, u'Yum!')

    # ===================
    # Regulars commands:
    # ===================
    if not (nick in USERS_REGULAR or nick in USERS_OP or nick == OWNER):
        if DEBUG:
            weechat.prnt("", "not regular or higher")
        return OK

    # +timer split
    split_match = re.match(r'^\+timer split (.*)', message)
    if split_match:
        return timer_split(buffer, nick, split_match.group(1))

    # +timer add
    add_match = re.match(r'^\+timer add (-?\d+)', message)
    if add_match:
        return timer_add(buffer, nick, add_match.group(1))
    # +timer start
    if message.startswith('+timer start'):
        return timer_start(buffer, nick)
    # +timer stop
    if message == '+timer stop':
        return timer_stop(buffer, nick)
    # +timer restart
    if message == '+timer restart':
        return timer_restart(buffer, nick)
    # +timer report
    if message == '+timer report':
        return timer_report(buffer, nick)

    # +timer
    if message.startswith('+timer'):
        return timer_status(buffer, nick)

    if message == '+luck':
        return cone(buffer, nick)

    # ===================
    # OP commands
    # ===================
    if not (nick in USERS_OP or nick == OWNER):
        if DEBUG:
            weechat.prnt("", "not OP or higher")
        return OK

    match = re.match(r'^\+regular add (.*)', message)
    if match:
        return bot_regular(buffer, nick, match.group(1))
    match = re.match(r'^\+regular remove (.*)', message)
    if match:
        return bot_deregular(buffer, nick, match.group(1))
    if message == '+regulars':
        return bot_say(buffer, nick, str(USERS_REGULAR))
    if message.startswith('+mute'):
        return bot_mute(buffer, nick)
    if message.startswith('+unmute'):
        return bot_unmute(buffer, nick)

    # ===================
    # OWNER commands:
    # ===================
    if nick != OWNER:
        if DEBUG:
            weechat.prnt("", "not owner")
        return OK

    if message.startswith('+op'):
        return bot_op(buffer, nick, message)
    if message.startswith('+deop'):
        return bot_deop(buffer, nick, message)

    # nothing happened.
    return OK


def bot_callback(data, buffer, date, tags, displayed, highlight, prefix, message):
    """Forward messages from weechat to the bot."""
    if DEBUG:
        weechat.prnt("", "DEBUG: bot_callback -- {} -- {} -- {} -- {} -- {} -- {} -- {}".format(
            buffer,
            date,
            tags,
            displayed,
            highlight,
            prefix,
            message,
        ))
    message = message.strip()

    # ignore all messages that don't start with a "+"
    if not message.startswith(u'+'):
        return OK

    # clean up the nick
    nick = re.sub('[~@%]', '', prefix)

    # ignore all messages not from whitelisted users.
    if nick in USERS_BLACKLIST:
        return OK

    # actually do something.
    return bot_dispatch(buffer, nick, message)


if __name__ == '__main__' and import_ok:
    weechat.register("weechat_timer",
                     "frustbox",
                     "0.1",
                     "GPLv3",
                     "This is a small timer module, allowing to create a timer, '\
                     'start and stop it and even put in split times.",
                     "",
                     "")

    # have the bot listen in whitelisted networks and channels.
    for network in WHITELISTED_NETWORKS:
        for channel in WHITELISTED_CHANNELS:
            b = weechat.info_get('irc_buffer', '{},{}'.format(network, channel))
            weechat.hook_print(b, 'irc_privmsg', '', 1, 'bot_callback', '')
    # weechat.hook_signal('twitch,irc_out_privmsg', 'bot_handler_outgoing', '')
