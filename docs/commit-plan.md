# Kế hoạch commit (13/11/2026 – 23/11/2026)

Mỗi thành viên **tự commit trên máy của mình bằng tài khoản git của mình**, vào ngày mình thực sự làm việc đó.
Mục "Repository commits" trong `contribution/member-x.md` chỉ ghi link repo và tên tác giả để giảng viên tự
kiểm tra lịch sử. Khi có link, thay `[repository link to be added]` trong 3 file rồi chạy
`python docs/build_contributions.py`.

## 0. Cấu hình một lần (mỗi người)

```bash
git config user.name "Trieu Ngoc Van Anh"
git config user.email "<email của bạn>"
```

Nên dùng đúng họ tên như trong bản đóng góp để giảng viên lọc commit theo tác giả.

## 1. Gợi ý việc thật còn lại để commit

| Ngày (gợi ý) | Người | Việc thực hiện | File | Commit message gợi ý |
|---|---|---|---|---|
| 13–14/11 | Vân Anh | Rà lại threat model và ma trận phân quyền, sửa câu chữ nếu cần | `docs/dfd.svg`, `docs/build_report.py` (ch. 3, 4, 8) | `docs: review threat model and access-control matrix` |
| 13–14/11 | Thanh Tú | Chạy lại toàn bộ test trên máy mình, cập nhật evidence | `evidence/`, `tests/` | `test: rerun full security suite and refresh evidence` |
| 15–16/11 | Quốc Khánh | Rà lại phần cài đặt; sửa lỗi nhỏ nếu phát hiện khi chạy thử | `source/` | `fix: <mô tả lỗi>` hoặc `refactor: <mô tả>` |
| 17/11 | Vân Anh | Hoàn thiện bản đóng góp của mình (số giờ, phần tự mô tả) | `contribution/member-a.md` | `docs: complete contribution statement (Van Anh)` |
| 17/11 | Quốc Khánh | Hoàn thiện bản đóng góp của mình | `contribution/member-b.md` | `docs: complete contribution statement (Quoc Khanh)` |
| 17/11 | Thanh Tú | Hoàn thiện bản đóng góp của mình | `contribution/member-c.md` | `docs: complete contribution statement (Thanh Tu)` |
| 18–20/11 | Vân Anh, Quốc Khánh, Thanh Tú | Quay đoạn demo của mình (theo `report/Kich_ban_demo.docx`); người ghép video dán link | `demo-video-link.txt` | `docs: add demo video link` |
| 21/11 | Thanh Tú | Chạy test lần cuối trước khi nộp | `evidence/` | `test: final evidence run before submission` |
| 22/11 | Quốc Khánh | Build lại báo cáo và các bản đóng góp sau khi điền commit | `report/`, `contribution/*.pdf` | `docs: rebuild report and contribution PDFs` |
| 23/11 | Người nộp | Đóng gói và nộp | — | (không cần commit) |

Lưu ý: chỉ commit những gì mình thực sự làm. Nếu không có gì để sửa ở một bước, bỏ qua bước đó. Không chỉnh ngày
commit bằng `--date` hay `GIT_COMMITTER_DATE`.

## 2. Lệnh commit cơ bản

```bash
git pull
git add <các file đã sửa>
git commit -m "<message>"
git push
```
