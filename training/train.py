import argparse
import json
import os
import platform
import random
import time
import traceback
from pathlib import Path

import cv2
import numpy as np
import torch

from .config import TrainingConfig
from .data import crop, crop_spec, group_split, metrics, read_image, sha
from .model import make_model


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path,value):
    temp=path.with_suffix(path.suffix+".tmp")
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    temp.replace(path)


class Stopped(Exception):
    pass


def check_stop(directory,managed):
    if (directory/"stop.request").exists():
        raise Stopped()
    heartbeat=directory/"heartbeat"
    if managed and heartbeat.exists() and time.time()-heartbeat.stat().st_mtime>15:
        raise RuntimeError("Backend heartbeat expired")


def exclusive_lock(path):
    handle=path.open("a+b")
    if handle.tell()==0:
        handle.write(b"0");handle.flush()
    handle.seek(0)
    try:
        if os.name=="nt":
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise RuntimeError("Another training process holds the device lock")
    return handle


def negative_center(image,gt,min_distance,rng):
    h,w=image.shape
    for _ in range(1000):
        point=[float(rng.integers(w)),float(rng.integers(h))]
        if np.linalg.norm(np.subtract(point,gt))>=min_distance:
            return point
    corners=[(0,0),(w-1,0),(0,h-1),(w-1,h-1)]
    point=max(corners,key=lambda p:np.linalg.norm(np.subtract(p,gt)))
    if np.linalg.norm(np.subtract(point,gt))<min_distance:
        raise ValueError("No valid negative location")
    return point


def batches(rows,config,seed,device):
    rng=np.random.default_rng(seed)
    order=rng.permutation(len(rows))
    for start in range(0,len(rows),config["batch_size"]):
        samples=[[],[],[]]
        for index in order[start:start+config["batch_size"]]:
            row=rows[index]
            ref=read_image(row["ref_path"],row["ref_hash"])
            query=read_image(row["query_path"],row["query_hash"])
            native,size=crop_spec(row["ref_box"],config["crop_mode"],config)
            negative=negative_center(query,row["query_gt"],config["negative_min_distance"],rng)
            for target,image,center in zip(samples,[ref,query,query],[row["ref_center"],row["query_gt"],negative]):
                target.append(crop(image,center,native,size)[0])
        yield [torch.from_numpy(np.stack(items)[:,None]).float().div(255).to(device) for items in samples]


def evaluate(model,rows,config,directory,managed,export=False):
    model.eval()
    results=[]
    if export:
        (directory/"heatmaps").mkdir(exist_ok=True)
    for row in rows:
        check_stop(directory,managed)
        ref=read_image(row["ref_path"],row["ref_hash"])
        query=read_image(row["query_path"],row["query_hash"])
        native,size=crop_spec(row["ref_box"],config["crop_mode"],config)
        patch,_=crop(ref,row["ref_center"],native,size)
        start=time.perf_counter()
        pred,score,heat=model.predict(patch,query,native,size,config["device"])
        if not np.isfinite(score):
            raise ValueError("Non-finite model output")
        item={"pair_id":row["pair_id"],"folder":row["folder"],"gt":row["query_gt"],"prediction":pred,
              "error":float(np.linalg.norm(np.subtract(pred,row["query_gt"]))),"score":score,
              "pattern_type":row["pattern_type"],"tier":row["tier"],"seconds":time.perf_counter()-start}
        results.append(item)
        if export:
            # Fixed cosine [-1,1] color scale, not per-image rescaled confidence.
            color=cv2.applyColorMap(np.clip((heat+1)*127.5,0,255).astype(np.uint8),cv2.COLORMAP_TURBO)
            cv2.imwrite(str(directory/"heatmaps"/f"{row['pair_id']}.png"),color)
    return results,metrics(results)


def run(directory,managed=False):
    lock=exclusive_lock(directory.parent/"training.lock")
    try:
        config=TrainingConfig(**load(directory/"config.json")).model_dump()
        checks=load(directory/"integrity.json")
        for relative,expected in checks.items():
            if sha((directory/relative).read_bytes())!=expected:
                raise ValueError(f"Experiment integrity check failed: {relative}")
        manifest=load(directory/"dataset_manifest.json")
        split=load(directory/"split_manifest.json")
        if group_split(manifest["pairs"],config)!=split:
            raise ValueError("Split integrity/leakage check failed")
        train=[p for p in manifest["pairs"] if p["pair_id"] in split["train"]]
        val=[p for p in manifest["pairs"] if p["pair_id"] in split["validation"]]
        if config["device"]=="cuda" and not torch.cuda.is_available():
            raise RuntimeError("CUDA unavailable. Set ALIGNFAIL_TRAINING_PYTHON to the WSL CUDA environment, or choose CPU for a smoke test.")
        seed=config["seed"]
        random.seed(seed);np.random.seed(seed);torch.manual_seed(seed)
        torch.set_num_threads(2)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.benchmark=False
        torch.backends.cudnn.deterministic=True
        torch.use_deterministic_algorithms(True)
        env=load(directory/"environment.json")
        env.update(python=platform.python_version(),platform=platform.platform(),torch=torch.__version__,cuda=torch.version.cuda,
                   gpu=torch.cuda.get_device_name(0) if config["device"]=="cuda" else "CPU",numpy=np.__version__,opencv=cv2.__version__,
                   model="metric_patch_v1: shared CNN + GAP, dense context pooling; no legacy weights",padding="reflect101",raw_prediction_stride=4)
        save(directory/"environment.json",env)
        model=make_model(config).to(config["device"])
        optimizer=torch.optim.AdamW(model.parameters(),lr=config["lr"],weight_decay=config["weight_decay"])
        history=[];best=float("inf")
        for epoch in range(1,config["epochs"]+1):
            check_stop(directory,managed)
            model.train();loss_sum=0.;seen=0
            for a,p,n in batches(train,config,seed+epoch,config["device"]):
                check_stop(directory,managed)
                optimizer.zero_grad(set_to_none=True)
                loss=model.training_loss(a,p,n,config["margin"])
                if not torch.isfinite(loss):
                    raise ValueError("Non-finite training loss")
                loss.backward();optimizer.step()
                loss_sum+=loss.item()*len(a);seen+=len(a)
            checkpoint={"model":model.state_dict(),"optimizer":optimizer.state_dict(),"epoch":epoch,"config":config,"split_hash":split["hash"]}
            torch.save(checkpoint,directory/"last.tmp")
            (directory/"last.tmp").replace(directory/"last.pt")
            model.eval();val_loss=0.;val_seen=0
            with torch.no_grad():
                for a,p,n in batches(val,config,seed,config["device"]):
                    check_stop(directory,managed)
                    val_loss+=model.training_loss(a,p,n,config["margin"]).item()*len(a);val_seen+=len(a)
            _,scores=evaluate(model,val,config,directory,managed)
            current={"epoch":epoch,"train_loss":loss_sum/seen,"val_loss":val_loss/val_seen,"lr":optimizer.param_groups[0]["lr"],"metrics":scores}
            history.append(current);save(directory/"history.json",history)
            print(json.dumps(current),flush=True)
            if scores["Overall"]["median_error"]<best:
                best=scores["Overall"]["median_error"]
                torch.save(checkpoint,directory/"best.tmp");(directory/"best.tmp").replace(directory/"best.pt")
        model.load_state_dict(torch.load(directory/"best.pt",map_location=config["device"],weights_only=True)["model"])
        predictions,scores=evaluate(model,val,config,directory,managed,export=True)
        save(directory/"predictions.json",predictions);save(directory/"metrics.json",scores)
        save(directory/"result.json",{"status":"completed"})
    finally:
        lock.close()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--experiment",type=Path,required=True)
    parser.add_argument("--managed",action="store_true")
    args=parser.parse_args()
    try:
        run(args.experiment.resolve(),args.managed)
    except Stopped:
        save(args.experiment/"result.json",{"status":"stopped"})
        print("Training stopped; completed checkpoints retained.",flush=True)
    except Exception as exc:
        save(args.experiment/"result.json",{"status":"failed","error":str(exc)})
        traceback.print_exc()
        raise SystemExit(1)


if __name__=="__main__":
    main()
