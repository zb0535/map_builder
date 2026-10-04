"""MapBuilder GUI 진입점. 배포 시 MapBuilder.exe로 빌드한다.

입력: 지역명, 저장 폴더, 선택적 파일 이름, 분할 간격
출력: 새 폴더 안에 .graphml 1개. 웹서버/API/러닝 라우터는 실행하지 않는다.
"""
from __future__ import annotations

import argparse
import multiprocessing as mp
import os
from pathlib import Path
import queue
import subprocess
import sys
import time

from builder_core import cleanup_stage, new_job, worker_entry


def open_folder(path: str) -> None:
    # 사용자 입력을 shell=True로 실행하지 않는다. 경로에 공백/한글이 있어도 안전하게 전달한다.
    if os.name == "nt":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


class MapBuilderApp:
    def __init__(self, root, worker_target=worker_entry):
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
        self.root, self.tk, self.ttk = root, tk, ttk
        self.filedialog, self.messagebox = filedialog, messagebox
        self.worker_target = worker_target
        self.context = mp.get_context("spawn")
        self.process = self.events = self.job = self.outcome = None
        self.cancelling = self.closing = False
        self.last_folder = None
        self.started = 0.0
        self.root.title("MapBuilder · 지역별 GraphML 생성기")
        self.root.geometry("780x650")
        self.root.minsize(680, 600)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TButton", padding=(12, 7))
        style.configure("Title.TLabel", font=("Malgun Gothic", 19, "bold"))
        style.configure("Muted.TLabel", foreground="#536574")
        self.place = tk.StringVar(value="광주광역시 북구 용봉동")
        self.destination = tk.StringVar(value=str(Path.home()))
        self.output_name = tk.StringVar(value="")
        self.segment = tk.StringVar(value="50")
        self.tile_large_area = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="지역과 저장 폴더를 정한 뒤 지도 생성을 누르세요.")
        self.elapsed = tk.StringVar(value="")
        frame = ttk.Frame(root, padding=22)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(10, weight=1)
        ttk.Label(frame, text="지역 지도 만들기", style="Title.TLabel").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(frame, text="지역명 입력 → 지도 생성 → GraphML 파일만 프로젝트에 사용", style="Muted.TLabel").grid(row=1, column=0, columnspan=3, sticky="w", pady=(6,18))
        self.inputs = []
        for row, label, variable in [(2,"지역명",self.place), (3,"저장 폴더",self.destination), (4,"파일 이름 (선택)",self.output_name)]:
            ttk.Label(frame, text=label).grid(row=row,column=0,sticky="w",padx=(0,12),pady=7)
            entry = ttk.Entry(frame, textvariable=variable)
            entry.grid(row=row,column=1,sticky="ew",pady=7)
            self.inputs.append(entry)
        self.choose_button = ttk.Button(frame,text="폴더 선택",command=self.choose_folder)
        self.choose_button.grid(row=3,column=2,padx=(8,0))
        ttk.Label(frame,text="비우면 지역명 사용",style="Muted.TLabel").grid(row=4,column=2,padx=(8,0))
        ttk.Label(frame,text="최대 간선 길이").grid(row=5,column=0,sticky="w",pady=7)
        self.spacing = ttk.Spinbox(frame,from_=10,to=50,increment=10,textvariable=self.segment,width=8)
        self.spacing.grid(row=5,column=1,sticky="w")
        self.inputs.append(self.spacing)
        ttk.Label(frame,text="m (10~50)",style="Muted.TLabel").grid(row=5,column=2,sticky="w")
        self.tile_check = ttk.Checkbutton(frame, text="큰 지역 자동 타일 분할 (100km² 초과용 · 2km 겹침)", variable=self.tile_large_area)
        self.tile_check.grid(row=6, column=0, columnspan=3, sticky="w", pady=(5, 2))
        self.inputs.append(self.tile_check)
        buttons = ttk.Frame(frame)
        buttons.grid(row=7,column=0,columnspan=3,sticky="ew",pady=(18,10))
        self.start_button = ttk.Button(buttons,text="지도 생성",command=self.start)
        self.start_button.pack(side="left")
        self.cancel_button = ttk.Button(buttons,text="취소",command=self.cancel,state="disabled")
        self.cancel_button.pack(side="left",padx=8)
        self.open_button = ttk.Button(buttons,text="결과 폴더 열기",command=self.open_result,state="disabled")
        self.open_button.pack(side="right")
        self.progress = ttk.Progressbar(frame,mode="indeterminate")
        self.progress.grid(row=8,column=0,columnspan=3,sticky="ew",pady=(0,8))
        ttk.Label(frame,textvariable=self.status,wraplength=710).grid(row=9,column=0,columnspan=3,sticky="w",pady=(0,8))
        self.log = tk.Text(frame,height=11,wrap="word",state="disabled",font=("Malgun Gothic",10),background="#f4f7fa",relief="flat",padx=10,pady=10)
        self.log.grid(row=10,column=0,columnspan=3,sticky="nsew")
        ttk.Label(frame,textvariable=self.elapsed,style="Muted.TLabel").grid(row=11,column=0,columnspan=3,sticky="e",pady=(6,0))
        ttk.Label(frame,text="인터넷 연결 필요 · 동/읍/면 단위 권장 · 큰 지역은 타일 모드를 사용합니다.\n지도 데이터 © OpenStreetMap contributors / ODbL",style="Muted.TLabel").grid(row=12,column=0,columnspan=3,sticky="w",pady=(10,0))
        self.root.after(120,self.poll)

    def append(self, text):
        self.log.configure(state="normal")
        self.log.insert("end",text+"\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def choose_folder(self):
        folder = self.filedialog.askdirectory(title="GraphML 결과 폴더를 저장할 위치",mustexist=True)
        if folder:
            self.destination.set(folder)

    def set_busy(self, busy):
        for widget in [*self.inputs,self.choose_button,self.start_button]:
            widget.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="normal" if busy else "disabled")
        self.open_button.configure(state="disabled" if busy or not self.last_folder else "normal")
        if busy:
            self.progress.start(12)
        else:
            self.progress.stop()

    def start(self):
        if self.process is not None:
            return
        try:
            self.job = new_job(self.place.get(),self.destination.get(),self.output_name.get(),self.segment.get(),
                               tile_large_area=self.tile_large_area.get())
        except (ValueError,OSError) as exc:
            self.messagebox.showerror("입력 확인",str(exc),parent=self.root)
            return
        self.outcome = None
        self.cancelling = False
        self.events = self.context.Queue()
        self.process = self.context.Process(target=self.worker_target,args=(self.job,self.events),daemon=True)
        self.started = time.monotonic()
        self.set_busy(True)
        self.status.set("지도 생성을 시작합니다…")
        self.append(f"\n지역: {self.job['place']}\n결과 폴더: {self.job['final']}")
        try:
            self.process.start()
        except Exception as exc:
            self.append(f"작업 프로세스를 시작할 수 없습니다: {exc}")
            self.events.close()
            self.events = self.process = None
            self.status.set("실행 실패 — 로그를 확인해주세요.")
            self.set_busy(False)

    def cancel(self):
        if self.process is not None and not self.cancelling:
            self.cancelling = True
            self.status.set("취소 중… 작업 프로세스를 종료하고 임시 파일을 정리합니다.")
            self.cancel_button.configure(state="disabled")
            if self.process.is_alive():
                self.process.terminate()

    def poll(self):
        if self.process is not None:
            self.elapsed.set(f"경과 {int(time.monotonic()-self.started)}초")
            if not self.cancelling:
                # 자식 프로세스가 Tk 객체를 만지지 않는다. 모든 GUI 변경은 이 메인 스레드에서 수행.
                try:
                    while True:
                        kind,data = self.events.get_nowait()
                        if kind == "progress":
                            self.status.set(data)
                            self.append(data)
                        elif kind in {"done","error"}:
                            self.outcome = (kind,data)
                except queue.Empty:
                    pass
            if not self.process.is_alive():
                self.process.join(timeout=0)
                # 직전 get_nowait 이후 종료한 자식의 마지막 메시지까지 받는다.
                if not self.cancelling and self.outcome is None:
                    try:
                        while True:
                            kind,data = self.events.get(timeout=0.2)
                            if kind in {"done","error"}:
                                self.outcome = (kind,data)
                                break
                            self.append(str(data))
                    except queue.Empty:
                        pass
                self.finish()
        if not (self.closing and self.process is None):
            self.root.after(120,self.poll)
        else:
            self.root.destroy()

    def finish(self):
        finished_file = Path(self.job["final"]) / ("manifest.json" if self.job.get("tile_large_area") else self.job["filename"])
        if self.cancelling:
            try:
                cleanup_stage(self.job)
            except OSError as exc:
                self.append(f"임시 폴더 정리 실패: {exc}")
            if finished_file.is_file():
                # 저장 완료 직후 취소를 눌렀다면 완성된 파일을 지우지 않는다.
                self.last_folder = self.job["final"]
                self.status.set("취소 요청 전에 저장이 완료되었습니다. 완성된 파일은 보존했습니다.")
            else:
                self.status.set("취소했습니다. 기존 지도 파일은 변경하지 않았습니다.")
        elif self.outcome and self.outcome[0] == "done":
            data = self.outcome[1]
            self.last_folder = data["folder"]
            if data.get("schema") == "running-loop-tile-manifest-v1":
                self.status.set(f"완료 · {data['tiles']}개 GraphML 타일 / {data['area_km2']:.2f}km² / 2km 겹침")
                self.append(f"검증 완료: {data['manifest']}\nmanifest.json과 모든 .graphml 타일을 함께 보관하세요.")
            else:
                self.status.set(f"완료 · 노드 {data['nodes']:,}개 / 간선 {data['edges']:,}개 / 최대 길이 {data['max_edge_m']:.2f}m")
                self.append(f"검증 완료: {data['file']}\n이 .graphml 파일만 다른 프로젝트에 사용하면 됩니다.")
        else:
            message = self.outcome[1]["message"] if self.outcome else f"작업이 비정상 종료됐습니다 (종료 코드 {self.process.exitcode})."
            detail = self.outcome[1].get("detail","") if self.outcome else ""
            self.status.set("생성 실패 — 지역명/인터넷 연결을 확인하고 다시 시도하세요.")
            self.append(message+"\n"+detail)
            try:
                cleanup_stage(self.job)
            except OSError as exc:
                self.append(f"임시 폴더 정리 실패: {exc}")
        self.events.close()
        self.events = self.process = None
        self.set_busy(False)

    def open_result(self):
        if self.last_folder:
            try:
                open_folder(self.last_folder)
            except OSError as exc:
                self.messagebox.showerror("폴더 열기 실패",str(exc),parent=self.root)

    def on_close(self):
        if self.process is not None:
            if not self.messagebox.askyesno("작업 종료","생성 중입니다. 작업을 취소하고 종료할까요?",parent=self.root):
                return
            self.closing = True
            self.cancel()
        else:
            self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="지역별 GraphML 지도 생성기")
    parser.add_argument("--self-test",metavar="REPORT_JSON",help="배포 검증용: 인터넷 없이 지도 처리 및 Tk 기동 검사")
    parser.add_argument("--gui-smoke",metavar="REPORT_JSON",help="배포 검증용: 실제 창 생성/종료 검사")
    args = parser.parse_args()
    if args.self_test:
        from self_test import run_self_test
        return run_self_test(Path(args.self_test))
    import tkinter as tk
    root = tk.Tk()
    app = MapBuilderApp(root)
    if args.gui_smoke:
        import json
        def finish_smoke():
            Path(args.gui_smoke).write_text(json.dumps({"ok":True,"title":root.title(),"default_place":app.place.get()},ensure_ascii=False),encoding="utf-8")
            root.destroy()
        root.after(400,finish_smoke)
    root.mainloop()
    return 0


if __name__ == "__main__":
    # PyInstaller로 만든 Windows EXE에서 자식 프로세스가 GUI를 반복 실행하지 않게 필수 설정.
    mp.freeze_support()
    raise SystemExit(main())
