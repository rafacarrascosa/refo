#  Copyright 2012 Machinalis S.R.L.
#
#  Author: Rafael Carrascosa <rcarrascosa@machinalis.com>
#
#  This file is part of REfO.
#
#  REfO is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation version 3 of the License, or
#  (at your option) any later version.
#
#  REfO is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with REfO.  If not, see <http://www.gnu.org/licenses/>.

import copy
from instructions import Atom, Accept, Split, Save


class RefoThread(object):
    """
    This class carries the per-thread information to implement a virtual
    machine aproach to regular expressions. ie, instances of this run inside
    an instance of VirtualMachine.
    """
    def __init__(self, pc):
        self.pc = pc
        self.state = {}
        self.i = 0    # FIXME: `i` is the same for every thread

    def step(self):
        """
        Take single epsilon transitions.
        The return value is a list of threads that must keep being executed.
        ie, if the instruction is Save, then `[self]` is returned, and if
        the instruction is Split then [self, other] is returned.
        """
        assert not isinstance(self.pc, (Atom, Accept))
        assert isinstance(self.pc, (Split, Save)), "Unknown instruction"
        ret = []
        if isinstance(self.pc, Split):
            s1 = self.pc.next
            s2 = self.pc.split
            self.pc = s1
            ret.append(self.copy(s2))
        else:  # Is a Save instruction
            self.state[self.pc.record] = self.i
            self.pc = self.pc.next
        return ret

    def feed(self, x):
        """
        Take a transition that involves consuming a symbol
        """
        assert self.idle()
        self.i += 1
        if isinstance(self.pc, Accept) or not self.pc.comparison_function(x):
            self.pc = None
        else:
            self.pc = self.pc.next

    def copy(self, pc):
        c = RefoThread(pc)
        c.state = copy.deepcopy(self.state)
        c.i = self.i
        return c

    def idle(self):
        return isinstance(self.pc, Atom) or isinstance(self.pc, Accept)

    def accepts(self):
        return isinstance(self.pc, Accept)

    def overlaps(self, other):
        return self.pc == other.pc

    def is_alive(self):
        return self.pc != None


class VirtualMachine(object):
    """
    A virtual machine to implement regular expressions.
    A regular expresion is compiled into a special program code and then run
    using a virtual machine specially made for that pourpose.
    It's a Thompson-like implementation (polynomial complexity), that respects
    thread priority (for ambiguous submatchings).
    Also, it does not requiere to have a sequence to be run, it can be feeded
    one symbol at a time.
    If the code has epsilon-cycles, ie, cyles of instructions that do not
    consume symbols then a thread running over that cycle does only one
    iteration and then is dropped(removed from the thread pool).
    """
    def __init__(self, code):
        self.code = code
        self.reset()

    def reset(self):
        thread = RefoThread(self.code)
        self.threads = [thread]

    def do_epsilon_transitions(self):
        """
        Takes epsilon transitions until all threads are idle (waiting to
        consume a symbol).
        """
        new = []
        current = self.threads
        current.reverse()
        # In this cycle the last thread in `current` has highest priority
        seen = set()
        while current:
            thread = current.pop()
            if thread.idle():
                self._add(new, thread)
            else:
                if thread.pc in seen:
                    continue
                seen.add(thread.pc)
                split = thread.step()
                for t in split:
                    current.append(t)
                # appending `thread` last ensures it keeps highest priority
                current.append(thread)
        self.threads = new

    def feed(self, x):
        """
        Takes all the transitions that involve consuming a symbol.
        Or, feeds a symbol to every thread in the VM.
        It's requiered that every thread is in idle state to call this method.
        """
        new = []
        for thread in self.threads:
            thread.feed(x)
            self._add(new, thread)
        self.threads = new

    def accepting_state(self, default):
        """
        Returns the state (affected by `Save` for example) of the accepting
        thread with highest priority or `default` if there is not such thread.
        """
        for t in self.threads:
            if t.accepts():
                return t.state
        return default

    def cutoff(self):
        """
        Looks for an accepting thread and then cuts-off threads of lower
        priority than that (including itself).
        If there are no accepting threads then it does nothing.
        """
        for i, t in enumerate(self.threads):
            if t.accepts():
                self.threads = self.threads[:i]
                return

    def is_alive(self):
        """
        Returns True if it is still possible to make a higher priority match by
        feeding more symbols. If not, it returns False.
        """
        return len(self.threads) != 0

    def _add(self, xs, thread):
        """
        Adds a thread `thread` to a thread queue `xs` unless `thread` has
        stopped or it overlaps with another thread in `xs`.
        """
        # This "dropping" of some threads is what makes this algorithm to be
        # polynomial and not exponential in complexity, because this way it's
        # ensured that there will never be more threads than instructions in
        # the code.
        if thread.is_alive() and all(not thread.overlaps(x) for x in xs):
            xs.append(thread)
