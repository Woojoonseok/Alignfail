# AlignFail AI Workspace — first integrated implementation

This is an **experimental**, local-only addition to Dataset Studio. It couples:
1. Human-classified **Template** images with white-cross GT annotations;
2. Separately held-out **REF–FAIL** Test pairs (REF ROI and FAIL Query);
3. Newly completed **Incoming** production images, whose GT/class need review.

**Not yet production validated:** RTX 4090/Qwen inference, real SEM Top-K recall, novel-class thresholds, 1px localization, and trained feature correlation are not measured in this release. Do not interpret the current NCC peak as verified ground truth.

## Quick start (Windows + WSL, RTX 4090)

In WSL, use Python 3.12 and Node 22. Existing Dataset Studio backend environment remains unchanged.

```bash
# Once, for the GPU inference environment:
python3.12 -m venv .vlm-venv
# Install a CUDA PyTorch wheel matching your GPU driver/toolkit from https://pytorch.org/
.vlm-venv/bin/python -m pip install -r template_bank/requirements.txt
.vlm-venv/bin/python -m pip install opencv-python-headless
.vlm-venv/bin/python -c "import torch; assert torch.cuda.is_available()"

# Launch backend with the dedicated GPU python path
export ALIGNFAIL_VLM_PYTHON="$PWD/.vlm-venv/bin/python"
bash scripts/start-wsl.sh

# For frontend source changes, rebuild:
npm --prefix frontend ci
npm --prefix frontend run build
```

**Safety:** back up `.studio/` before updating. Model weights, factory images and GPU runtime files are not uploaded to GitHub. The default Qwen3-VL-Embedding-2B is downloaded when first used; in offline networks, pre-cache it in Hugging Face's cache. The current UI uses the default ID; alternative model paths can be supplied through the API.

Open **AI Workspace** in the side navigation. Paths below are **server/WSL filesystem paths**, not browser device paths. Existing top-right Train folder upload can still be used for browser selection.

## Data layout

```text
/mnt/d/Alignfail/
  Template/                 # each immediate subfolder is a human class
    Class_A/
      a_with_white_cross.png
      a_marked_success.png
    Class_B/
      b.png
  TestPairs/                # every leaf has exactly ONE filename containing REF
    pair_001/
      image_REF.png
      image_FAIL.png
    pair_002/
      ref.png
      query.png
  Incoming/                 # arbitrary nested files, initially without trusted class
    new_001.png
    new_002.png
```

Click **Register** on each section. Test pairs are saved with **dataset_split=test**, **sample_role=pair**, one Reference image and one Fail Query. Their coordinates are **NOT** auto-filled from FAIL annotations. The Train importer retains human folder names as class labels; Incoming import intentionally leaves class empty.

Test and Train input roots must be disjoint. Special incoming/test imports reject source-directory collisions. Original files remain untouched. Incoming class publication copies a **reviewed, verified image** into the private workspace `.studio/ai_workspace/<project_id>/curated/<class>/`.

## Mandatory annotation procedure

**Template Train:**
1. Register existing Template class folder, then run **Train 십자선 GT 후보 생성**. The candidate detector uses the existing `detect_markings()` from Dataset Studio.
2. Open a Template in AI Workspace. If the white cross exists, inspect the intersection and click **자동 GT 확인**. Incorrect automatic candidates should be manually corrected by clicking the image. If no white cross is present, click the true target center manually.
3. For marked images, use the existing Pair Explorer Clean UI to remove the cross *without editing the original*; check the Clean preview. Only **human-reviewed GT** with valid Clean images, or human-reviewed **marker-free** images, contribute to the model's Template Bank. The GT remains in **original raw image pixel coordinates**.

**Test pairs:**
1. Run **Test REF ROI 자동 검출**. Verify white-box ROI in Pair Explorer and correct manually if needed.
2. The FAIL Query crosshair (if any) is the old algorithm's prediction, **not GT**. For a valid localization-error metric, a reviewer must click the actual target on the FAIL image (in original coordinates).
3. VLM uses the Test REF's ROI to retrieve existing Template classes. Test FAIL is used only as a spatial matching search image, and the Test Set never becomes Train.

**Incoming images:**
1. Import images and run VLM search to obtain Top-K known-class proposals and **candidate** x/y.
2. Manually choose/correct target GT, inspect class suggestions and save. For truly new patterns, enter a **new class name**, then save GT.
3. Click **검토 완료 → 클래스 폴더 저장**. The backend checks manual GT, white-cross cleaning requirement, source SHA256, revision, and class name; copies into the managed physical class folder and records `publish_ledger.json`.
4. Only a published Incoming pair may subsequently enter the VLM bank. The incoming original is never moved, modified or deleted. A published class cannot be reassigned via the same publish endpoint: a separate revoke operation is needed for future corrections.

## AI matching: algorithm and semantics

- **Retrieval:** Qwen3-VL-Embedding-2B on GT-centered `patch_size=160` Template crops vs Test REF white-box *interior* crops, or Incoming GT crops when available. Incoming images without GT use a weak global-image embedding until reviewed.
- **Class score:** mean cosine of each class's Top-3 template embeddings. Returns Top-K classes and Top-K individual templates, not a calibrated posterior.
- **Spatial baseline:** `cv2.matchTemplate` with `TM_CCOEFF_NORMED` on the **entire FAIL Query** (Test) or Incoming image, anchored on each retrieved Template's reviewed GT. Peak locations are converted back into raw Query pixel coordinates. Flat templates and too-small Queries do not return fabricated coordinates.
- **Evaluation:** external predictions can be analyzed using `python -m template_bank evaluate` after independently verified Test FAIL GT is recorded. The current UI does not automatically execute the previously trained Triplet localization model.
- **Novel class:** prototype UI allows manual creation via class-name entry; automatic calibrated novel-category detection and cluster curation are *not yet* integrated.

Because SEM has repeating patterns and varying scale/rotation, the NCC result is only a **baseline**. A future implementation should compare REF-only / Template-only / combined localization, replace NCC with shared-backbone spatial correlation + offset head, and evaluate candidate recall and pixel error on a disjoint development set before touching the final 150-pair Test set.

## API

- `POST /api/projects/{project_id}/ai/import/test` body `{"root_directory":"/absolute/path"}`
- `POST /api/projects/{project_id}/ai/import/incoming` same body
- `GET /api/projects/{project_id}/ai/overview`
- `POST /api/projects/{project_id}/ai/run` body `{"model":"Qwen/Qwen3-VL-Embedding-2B","batch_size":1,"top_k":5,"patch_size":160}`
- `GET /api/projects/{project_id}/ai/jobs/{job_id}`
- `POST /api/projects/{project_id}/ai/approve` for proposed class linkage (revision checked; Test stays Test)
- `POST /api/projects/{project_id}/ai/publish` for a manually reviewed Incoming image to a physical class folder

The GT and cross/box annotation endpoints are reused from Dataset Studio. GPU computation runs as a dedicated local subprocess, with per-job results/logs in the project-specific private `.studio/ai_workspace` path. One running job per project is supported in a single server process. If the GPU worker fails, inspect its `jobs/<job_id>/worker.log`.

## Verification

```bash
python -m pytest -q backend/tests/test_ai_workspace.py backend/tests/test_template_bank.py
npm --prefix frontend ci
npm --prefix frontend run build
```

GitHub Actions CI runs CPU-only synthetic tests and TypeScript/Vite build; it does **not** verify Qwen's runtime behavior, CUDA memory or accuracy on private imagery.
