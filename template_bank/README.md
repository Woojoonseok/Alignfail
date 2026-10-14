# AlignFail Template Bank — experimental Phase 1

**Goal:** match 150 held-out Reference–Fail pairs to existing human-labeled Template classes, then stage new process-complete (Success/Fail) images as existing-class or novel-class **candidates**.

This is an **isolated CLI** extension to the existing Dataset Studio. It does not modify its database, human class labels, training pipelines or original images. It does **not** perform Align Key localization; the Test evaluation command expects predictions made by an existing localization model. Actual RTX 4090 runtime and factory data accuracy **have not been measured**.

## Setup — RTX 4090 / WSL

Use Python 3.12 and a separate virtual environment with CUDA-enabled PyTorch (install a compatible wheel for your local driver/CUDA setup).

```bash
python -m pip install -r template_bank/requirements.txt
python -m template_bank --help
```

Default image model: [Qwen3-VL-Embedding-2B](https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B), loaded by `sentence-transformers`. It supports image embeddings using PIL objects and `{"image": image}` input. The default device is `cuda`, batch size 2. If GPU memory is insufficient, lower `--batch-size` to 1. You may download the model in advance and use `--model /path/to/local/model` for company networks without internet. The same model identifier/path must be supplied on every `index`, `match-test` and `ingest` run. Model weights are not included.

## File layout

```text
/safe/classes/
  Class_A/
    clean_success_001.png
  Class_B/
    clean_success_002.png
/safe/test/
  pairs.csv
  ref_001.png
  fail_001.png
/safe/incoming/
  new_image_001.png
```

`classes/` contains only **human-verified** training/template data. Test REF/FAIL images must never enter that folder. The `incoming/` folder may contain Success or Fail: **outcome is metadata, not a pattern label**.

The Test CSV has one row per pair, with paths relative to its own directory or absolute paths.

```csv
pair_id,reference,fail,roi_x0,roi_y0,roi_x1,roi_y1,expected_class
P001,ref_001.png,fail_001.png,90,87,213,212,Class_A
```

ROI describes the Reference's pattern target in **original pixel coordinates**, right/bottom exclusive; it is not a ground-truth location in the Fail image. `expected_class` is optional and must come from independent manual review. Leave all four ROI values blank if unknown: this will use global image embedding as a weak baseline. For actual SEM imagery, preprocess the Reference white box and template crosshair markings using Dataset Studio's reviewed Clean files *before* encoding, and evaluate a spatial reranker as a next step.

## Commands

```bash
# 1. Build feature bank from existing, human-classified template folders.
python -m template_bank index --classes /safe/classes --bank /safe/results/bank

# 2. Match only held-out Test References to Top-K template classes and images.
#    Paired Fail images are retained as links but NEVER embedded or trained.
python -m template_bank match-test --pairs /safe/test/pairs.csv \
  --bank /safe/results/bank --output /safe/results/test_matches.json --topk 10

# 3. Stage new process-complete images. Default: human review for *all*.
python -m template_bank ingest --incoming /safe/incoming \
  --bank /safe/results/bank --stage /safe/results/review

# 4. After independent development-set calibration, optional candidates:
python -m template_bank ingest --incoming /safe/next_batch \
  --bank /safe/results/bank --stage /safe/results/review \
  --accept-score 0.85 --accept-margin 0.04

# 5. Evaluate externally produced localization predictions (when Fail GT exists):
python -m template_bank evaluate --matches /safe/results/test_matches.json \
  --predictions /safe/results/predictions.csv --output /safe/results/metrics.json
```

**Thresholds above are uncalibrated examples, not recommended production thresholds.** With no thresholds, every unique incoming image receives status `review_required`. With both thresholds provided, results are `existing_candidate`, `novel_candidate`, or `ambiguous`. None are automatically promoted to the canonical classes. New-type candidates are staged in `novel_candidate/_review`, not assigned invented class identities. Reviewers should approve or create classes manually and rerun `index`.

The staging process copies images under SHA256-derived filenames without deleting or changing the source. A JSON ledger saves paths, hashes, proposed class and Top-K neighbors. Re-running with the same stage is content-idempotent for recorded images. This CLI is batch-based, not a continuously running watcher: use Task Scheduler/cron to invoke it periodically after verifying the workflow. Exact SHA collision of Test vs bank is blocked during `match-test`; near-duplicate and lot/process leakage still require additional checks.

## Evaluation format and limitations

An external Align Fail localization model can produce `predictions.csv`:

```csv
pair_id,pred_x,pred_y,gt_x,gt_y
P001,151,153,152,151
```

The ground truth must be **manually verified in original Fail-image coordinates**; the previous algorithm's drawn crosshair is not accepted as ground truth. `evaluate` produces class Top-1 / Top-K metrics for pairs with `expected_class` and localization median/mean error plus within-5px/10px for pairs with valid numeric GT and predictions. Unavailable scores are `null`, not fabricated.

**Planned integration:** (1) export immutable Test REF/FAIL manifests and verified class images from Dataset Studio, (2) GPU background job and thumbnail candidate review UI, (3) a calibrated unknown-class threshold and spatial template reranker for repeated SEM textures, (4) invoke validated localization checkpoint and report end-to-end test results. Do not tune thresholds/model choices using the final 150-pair held-out Test set.

**Data policy:** The GitHub repository is public. Never commit company images, dataset DB, .studio, weight files, private paths, or experiment output.
