#!/usr/bin/python2.7

from collections import deque

import matplotlib.pyplot as plt

import argparse
import numpy
import Queue
import sys


def enum(**enums):
  return type('Enum', (), enums)


# Event queue.
class EventQueue(object):

  def __init__(self):
    self._root = None
    self._queue = Queue.PriorityQueue()

  def add(self, ts, callback):
    self._queue.put((ts, callback))

  def run(self, runfor):
    global clock_ts

    while not self._queue.empty():
      work = self._queue.get()
      clock_ts = work[0]
      work[1]()


# The processor.
class Processor(object):

  def __init__(self, event_queue, lifo):
    self._lifo = lifo
    self._event_queue = event_queue
    self._queue = deque()
    self._queue_last_modification_time = 0
    self._queue_total_len = 0
    self._servicing = None
    self._total_none_servicing_duration = 0
    self._last_none_schedule_time = 0
    self._total_customers_in_system = 0
    self._last_customer_event_time = 0
    self._wasted_cpu_time = 0
    self._start_slice_time = 0
    self._execution_times = []
    self._i = 0

  def _get_execution_time(self):
    if self._i >= len(self._execution_times):
      self._execution_times = random.exponential(1.0 / args.U, 512)
      self._i = 0

    self._i += 1
    return self._execution_times[self._i - 1]

  def _maintain_stats(self):
    self._queue_total_len += len(self._queue) * (
        clock_ts - self._queue_last_modification_time)
    self._queue_last_modification_time = clock_ts

    self._total_customers_in_system += self.get_customers_in_system() * (
        clock_ts - self._last_customer_event_time)
    self._last_customer_event_time = clock_ts

  def is_busy(self):
    return self._servicing is not None

  def _schedule(self, customer):
    if self._servicing is None:
      self._total_none_servicing_duration += clock_ts - self._last_none_schedule_time

    self._servicing = customer
    customer.notify_running()
    self._start_slice_time = clock_ts
    self._execution_time = self._get_execution_time()
    self._event_queue.add(clock_ts + self._execution_time,
                          lambda: self._done(customer))

  def _schedule_next(self):
    assert self._servicing is not None

    if len(self._queue) > 0:
      if self._lifo:
        customer = self._queue.pop()
      else:
        customer = self._queue.popleft()

      self._schedule(customer)
    else:
      self._servicing = None
      self._last_none_schedule_time = clock_ts

  def get_customers_in_system(self):
    n = len(self._queue)

    if self._servicing is not None:
      n += 1

    return n

  def add(self, customer):
    self._maintain_stats()

    if self._servicing is None:
      self._schedule(customer)
    else:
      self._queue.append(customer)

  def _done(self, customer):
    # This might happen if the customer timed out before it is done. We do not
    # remove the "done" event from the event queue, so the done event will still
    # come in.
    if customer != self._servicing:
      return

    self._maintain_stats()
    self._servicing.notify_finished(self._execution_time)
    self._schedule_next()

  def remove_queue(self, customer):
    assert self._servicing is not customer
    self._maintain_stats()
    self._queue.remove(customer)

  def unschedule(self, customer):
    assert self._servicing == customer
    assert clock_ts == customer._deadline_ts
    self._maintain_stats()
    self._wasted_cpu_time += clock_ts - self._start_slice_time
    self._schedule_next()

  def get_mean_queue_length(self):
    self._maintain_stats()
    return self._queue_total_len / clock_ts

  def get_mean_customers_in_system(self):
    return self._total_customers_in_system / clock_ts

  def get_idle_fraction(self):
    return self._total_none_servicing_duration / clock_ts

  def get_wasted_cpu_time(self):
    return self._wasted_cpu_time


# The customer.
class Customer(object):
  _State = enum(FOETUS=1, WAITING=2, RUNNING=3, DONE=4)

  @classmethod
  def reset(cls):
    cls._total_waiting_duration = 0
    cls._total_running_duration = 0
    cls._total_system_duration = 0
    cls._total_finished = 0
    cls._total_timed_out = 0
    cls._total_canceled = 0
    cls._total_customers = 0
    cls._system_durations = []
    cls._next_id = 1

  def __init__(self, event_queue, processor, entry_ts):
    self._id = Customer._next_id
    Customer._next_id += 1
    self._processor = processor
    self._entry_ts = entry_ts
    self._deadline_ts = entry_ts + args.DEADLINE
    self._state = Customer._State.FOETUS
    event_queue.add(self._entry_ts, lambda: self._entry())
    event_queue.add(self._deadline_ts, lambda: self._deadline())

  def _log(self, text):
    if args.VERBOSE:
      print 'ts=%4.3f id=%d %s' % (clock_ts, self._id, text)

  def _entry(self):
    assert self._state == Customer._State.FOETUS
    assert self._entry_ts == clock_ts
    self._log('Enter')
    self._state = Customer._State.WAITING
    self._processor.add(self)

  def _done(self, timed_out):
    system_duration = clock_ts - self._entry_ts

    if not timed_out:
      Customer._system_durations.append(system_duration)

    Customer._total_system_duration += system_duration
    Customer._total_customers += 1
    self._state = Customer._State.DONE

  def _deadline(self):
    assert self._deadline_ts == clock_ts
    assert self._state != Customer._State.FOETUS

    # This happens when a customer finishes before timeout. We do not remove the
    # deadline event from the event queue, so it still comes in, but can be
    # ignored.
    if self._state == Customer._State.DONE:
      return

    self._log('Deadline. State: %d' % self._state)

    if self._state == Customer._State.WAITING:
      Customer._total_timed_out += 1
      self._processor.remove_queue(self)
    elif self._state == Customer._State.RUNNING:
      if args.NO_CANCEL:
        return

      Customer._total_canceled += 1
      self._processor.unschedule(self)
    else:
      raise 'This should never happen. Really!'

    self._done(True)

  def notify_running(self):
    assert self._state == Customer._State.WAITING
    self._log('Running')
    self._state = Customer._State.RUNNING
    Customer._total_waiting_duration += clock_ts - self._entry_ts

  def notify_finished(self, exec_time):
    assert self._state == Customer._State.RUNNING
    self._log('Finished')
    self._done(False)
    Customer._total_finished += 1
    Customer._total_running_duration += exec_time

  @classmethod
  def get_total_finished(cls):
    return cls._total_finished

  @classmethod
  def get_total_timed_out(cls):
    return cls._total_timed_out

  @classmethod
  def get_mean_waiting_time(cls):
    return cls._total_waiting_duration / cls._total_customers

  @classmethod
  def get_mean_execution_time(cls):
    return cls._total_running_duration / cls._total_finished

  @classmethod
  def get_mean_time_in_system(cls):
    return cls._total_system_duration / cls._total_customers

  @classmethod
  def get_system_durations(cls):
    return cls._system_durations

  @classmethod
  def get_total_canceled(cls):
    return cls._total_canceled


def p(title, num, expected=None, of=None):
  print ' ', title + ':', num,

  if of is not None:
    print '(%.2f%%)' % ((100.0 * num) / of),

  if expected is not None:
    print '(expected:', expected, 'delta: %.2f%%)' % (
        100.0 * abs(num - expected) / expected)
  else:
    print


def setup_customers(event_queue, processor):
  Customer.reset()

  ts = 0
  i = 0
  a = random.exponential(1.0 / args.L, args.RUNFOR * args.L * 2)

  while ts < args.RUNFOR:
    ts += a[i]
    i += 1
    Customer(event_queue, processor, ts)

  return i


def report(n, processor, lifo):
  qtype = 'LIFO' if lifo else 'FIFO'
  total_finished = Customer.get_total_finished()
  total_timed_out = Customer.get_total_timed_out()
  total_canceled = Customer.get_total_canceled()
  mean_execution_time = Customer.get_mean_execution_time()
  mean_waiting_time = Customer.get_mean_waiting_time()
  mean_time_in_system = Customer.get_mean_time_in_system()
  mean_customers_in_system = processor.get_mean_customers_in_system()
  mean_queue_length = processor.get_mean_queue_length()
  idle_fraction = processor.get_idle_fraction()
  wasted_cpu_time = processor.get_wasted_cpu_time()

  print 'System:'
  p('Queue type', qtype)
  p('traffic density', args.RHO)
  p('Run for', args.RUNFOR)
  print 'Customers:'
  p('#generated', n, args.RUNFOR * args.L)
  p('#finished', total_finished, of=n)
  p('#timed_out', total_timed_out, of=n)
  p('#canceled', total_canceled, of=n)
  p('mean execution time', mean_execution_time, 1 / args.U)

  if args.RHO >= 1:
    p('mean time in queue', mean_waiting_time)
    p('mean time in system', mean_time_in_system)
    p('mean number in system', mean_customers_in_system)
  else:
    p('mean time in queue',
      mean_waiting_time, 1 / (args.U - args.L) - 1 / args.U)
    p('mean time in system',
      mean_time_in_system, 1 / (args.U - args.L))
    p('mean number in system',
      mean_customers_in_system, args.RHO / (1 - args.RHO))

  print 'Processor:'
  p('mean queue length', processor.get_mean_queue_length())
  p('idle fraction', processor.get_idle_fraction(), 1.0 - args.RHO)
  p('wasted processor time', processor.get_wasted_cpu_time())
  print 'CSV:'
  print ' ', ','.join(map(str, [args.RHO, qtype, n, total_finished, total_timed_out,
    total_canceled, mean_execution_time, mean_time_in_system,
    mean_customers_in_system, mean_queue_length, idle_fraction,
    wasted_cpu_time]))
  print


def run(lifo):
  global random, clock_ts

  clock_ts = 0
  random = numpy.random.RandomState(42)
  event_queue = EventQueue()
  processor = Processor(event_queue, lifo)
  n = setup_customers(event_queue, processor)
  event_queue.run(args.RUNFOR)
  assert processor.get_customers_in_system() == 0
  report(n, processor, lifo)

  return Customer.get_system_durations()


def main():
  global args

  parser = argparse.ArgumentParser()
  parser.add_argument('--arrival_rate', default=10)
  parser.add_argument('--service_rate', default=20)
  parser.add_argument('--deadline', default=2)
  parser.add_argument('--runfor', default=3600)
  parser.add_argument('--save_fig')
  parser.add_argument('--verbose', action='store_true')
  parser.add_argument('--no_cancel', action='store_true')
  args = parser.parse_args()

  args.L = float(args.arrival_rate)
  args.U = float(args.service_rate)
  args.RHO = args.L / args.U
  args.RUNFOR = int(args.runfor)
  args.DEADLINE = float(args.deadline)
  args.VERBOSE = bool(args.verbose)
  args.NO_CANCEL = bool(args.no_cancel)

  a = run(False)
  b = run(True)
  plt.hist(
      [a, b], bins=numpy.arange(0, args.DEADLINE + 0.1, 0.1), color=['b', 'r'])
  plt.legend(['FIFO', 'LIFO'])
  plt.title('Traffic intensity %lf' % args.RHO)
  plt.xlabel('Total time in the system in seconds')
  plt.ylabel('Number of customers')

  if args.save_fig:
    plt.savefig(args.save_fig)
  else:
    plt.show()


if __name__ == '__main__':
  main()
