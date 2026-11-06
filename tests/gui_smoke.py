"""Optional real-Tk smoke check: PYTHONPATH=src python3 tests/gui_smoke.py.

Requires a graphical desktop and Tk. Not part of headless unittest discovery.
Opens a window, runs the fixed scenario through the service, checks presentation,
resizes, toggles trace, tests input validation, and closes automatically.
"""

from time import monotonic
import traceback

from tower_defense_optimizer.gui import OptimizerApp, tk


def main():
    if tk is None:
        raise SystemExit('Tk unavailable; see README.md installation and manual checklist.')
    root = tk.Tk()
    app = OptimizerApp(root)
    started = monotonic()
    failures = []
    phase = [0]

    def check():
        try:
            if monotonic() - started > 30:
                raise AssertionError('GUI smoke timed out: ' + app.status.get())
            if app.busy:
                root.after(100, check)
                return
            if phase[0] == 0:
                assert app.canvas.find_withtag('cell')
                app.expanded.set('4')
                app.seconds.set('')
                app.steps.set('2')
                app.start()
                assert app.busy
                assert str(app.run_button['state']) == 'disabled'
                phase[0] = 1
                root.after(100, check)
                return
            assert len(app.views) == 3, app.status.get()
            assert len(app.table.get_children()) == 3
            assert all(len(view.measures) == 6 for view in app.views)
            app.table.selection_set('2')
            app.select_result()
            assert 'Simple Hill Climbing' in app.recommendation.get()
            assert any(cell.kind == 'sniper' for cell in app.cells)
            app.trace_visible.set(True)
            app.toggle_trace()
            assert app.trace_box.frame.winfo_manager() == 'grid'
            trace = app.trace_box.get('1.0', 'end')
            assert trace.startswith('3. Simple Hill Climbing\n')
            assert 'Stage 0' in trace and 'Stage 1' in trace and 'Stage 2' not in trace
            app.table.selection_set('1')
            app.select_result()
            assert 'g=0, h=4, f=4' in app.trace_box.get('1.0', 'end')
            app.trace_visible.set(False)
            app.toggle_trace()
            assert not app.trace_box.frame.winfo_manager()
            root.geometry('900x700')
            root.update_idletasks()
            assert app.canvas.winfo_width() > 100
            assert len(app.canvas.find_withtag('cell')) == 100
            app.expanded.set('-1')
            app.start()
            assert not app.busy and 'Explored-state limit' in app.status.get()
            print('GUI smoke passed: startup, worker, compare-all, grid, metrics, row selection, '
                  'trace/A* scores, collapse, resize, validation, shutdown.')
        except Exception:
            failures.append(traceback.format_exc())
        root.destroy()

    root.after(200, check)
    root.mainloop()
    if failures:
        raise SystemExit('\n'.join(failures))


if __name__ == '__main__':
    main()
