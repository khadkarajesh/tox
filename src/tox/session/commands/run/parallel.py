import os
import sys
from collections import OrderedDict, deque
from threading import Event, Semaphore, Thread

from tox import reporter
from tox.config.parallel import ENV_VAR_KEY as PARALLEL_ENV_VAR_KEY
from tox.exception import InvocationError
from tox.util.main import MAIN_FILE
from tox.util.spinner import Spinner


def run_parallel(config, venv_dict):
    """here we'll just start parallel sub-processes"""
    live_out = config.option.parallel_live
    args = [sys.executable, MAIN_FILE] + config.args
    try:
        position = args.index("--")
    except ValueError:
        position = len(args)

    max_parallel = config.option.parallel
    if max_parallel is None:
        max_parallel = len(venv_dict)
    semaphore = Semaphore(max_parallel)
    finished = Event()

    show_progress = not live_out and reporter.verbosity() > reporter.Verbosity.QUIET

    with Spinner(enabled=show_progress) as spinner:

        def run_in_thread(tox_env, os_env, processes):
            output = None
            env_name = tox_env.envconfig.envname
            status = "skipped tests" if config.option.notest else None
            try:
                os_env[str(PARALLEL_ENV_VAR_KEY)] = str(env_name)
                args_sub = list(args)
                if hasattr(tox_env, "package"):
                    args_sub.insert(position, str(tox_env.package))
                    args_sub.insert(position, "--installpkg")
                with tox_env.new_action("parallel {}".format(tox_env.name)) as action:

                    def collect_process(process):
                        processes[tox_env] = (action, process)

                    print_out = not live_out and tox_env.envconfig.parallel_show_output
                    output = action.popen(
                        args=args_sub,
                        env=os_env,
                        redirect=not live_out,
                        capture_err=live_out,
                        callback=collect_process,
                        returnout=print_out,
                    )

            except InvocationError as err:
                status = "parallel child exit code {}".format(err.exit_code)
            finally:
                semaphore.release()
                finished.set()
                tox_env.status = status
                done.add(env_name)
                outcome = spinner.succeed
                if config.option.notest:
                    outcome = spinner.skip
                elif status is not None:
                    outcome = spinner.fail
                outcome(env_name)
                if print_out and output is not None:
                    reporter.verbosity0(output)

        threads = deque()
        processes = {}
        todo_keys = set(venv_dict.keys())
        todo = OrderedDict((n, todo_keys & set(v.envconfig.depends)) for n, v in venv_dict.items())
        done = set()
        try:
            while todo:
                for name, depends in list(todo.items()):
                    if depends - done:
                        # skip if has unfinished dependencies
                        continue
                    del todo[name]
                    venv = venv_dict[name]
                    semaphore.acquire(blocking=True)
                    spinner.add(name)
                    thread = Thread(
                        target=run_in_thread, args=(venv, os.environ.copy(), processes)
                    )
                    thread.daemon = True
                    thread.start()
                    threads.append(thread)
                if todo:
                    # wait until someone finishes and retry queuing jobs
                    finished.wait()
                    finished.clear()
            while threads:
                threads = [
                    thread for thread in threads if not thread.join(0.1) and thread.is_alive()
                ]
        except KeyboardInterrupt:
            reporter.verbosity0(
                "[{}] KeyboardInterrupt parallel - stopping children".format(os.getpid())
            )
            while True:
                # do not allow to interrupt until children interrupt
                try:
                    # putting it inside a thread so it's not interrupted
                    stopper = Thread(target=_stop_child_processes, args=(processes, threads))
                    stopper.start()
                    stopper.join()
                except KeyboardInterrupt:
                    continue
                raise KeyboardInterrupt


def _stop_child_processes(processes, main_threads):
    """A three level stop mechanism for children - INT (250ms) -> TERM (100ms) -> KILL"""

    # first stop children
    def shutdown(tox_env, action, process):
        action.handle_interrupt(process)

    threads = [Thread(target=shutdown, args=(n, a, p)) for n, (a, p) in processes.items()]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    # then its threads
    for thread in main_threads:
        thread.join()
