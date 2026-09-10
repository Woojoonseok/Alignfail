"""New shared-encoder Triplet baseline, deliberately distinct from legacy SupCon."""
import cv2
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F


class MetricPatch(nn.Module):
    stride = 4

    def __init__(self, embedding_dim=256):
        super().__init__()
        self.encoder = nn.Sequential(nn.Conv2d(1,16,3,padding=1),nn.ReLU(),nn.AvgPool2d(2),
                                     nn.Conv2d(16,32,3,padding=1),nn.ReLU(),nn.AvgPool2d(2),
                                     nn.Conv2d(32,embedding_dim,3,padding=1),nn.ReLU())

    def forward(self, patches):
        return F.normalize(self.encoder(patches).mean(dim=(-2,-1)),dim=1)

    def training_loss(self, anchor, positive, negative, margin):
        a,p,n = self(anchor),self(positive),self(negative)
        return torch.relu((1-(a*p).sum(1))-(1-(a*n).sum(1))+margin).mean()

    @torch.no_grad()
    def predict(self, reference_crop, query, native_size, input_size, device):
        # Query descriptors aggregate the same spatial context as REF GAP, rather than
        # comparing a large REF crop to a single tiny-receptive-field Query cell.
        scale = native_size / input_size
        h,w = query.shape
        nx,ny = int(np.floor((w-1)/(self.stride*scale)))+1,int(np.floor((h-1)/(self.stride*scale)))+1
        out_w,out_h = (nx-1)*self.stride+input_size,(ny-1)*self.stride+input_size
        if max(out_w,out_h)>4096:
            raise ValueError("Dense query input exceeds 4096 pixels; reduce adaptive resize or source resolution.")
        x = (np.arange(out_w,dtype=np.float32)-(input_size-1)/2)*scale
        y = (np.arange(out_h,dtype=np.float32)-(input_size-1)/2)*scale
        xx,yy = np.meshgrid(x,y)
        pixels = cv2.remap(query,xx,yy,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REFLECT_101)
        ref = self(tensor(reference_crop,device))
        features = self.encoder(tensor(pixels,device))
        pooled = F.avg_pool2d(features,kernel_size=input_size//self.stride,stride=1)
        scores = (F.normalize(pooled,dim=1)*ref[:,:,None,None]).sum(1)[0].cpu().numpy()
        # Feature-grid centers are anchored at raw (0,0), including resize scale.
        gx,gy = np.meshgrid(np.arange(w,dtype=np.float32)/(self.stride*scale),np.arange(h,dtype=np.float32)/(self.stride*scale))
        heat = cv2.remap(scores,gx,gy,cv2.INTER_LINEAR,borderMode=cv2.BORDER_REPLICATE)
        # Keep the final search grid at 4 raw pixels for every crop mode, so adaptive
        # resize does not silently receive a finer output search grid than fixed crops.
        candidates = heat[::4,::4]
        iy,ix = np.unravel_index(candidates.argmax(),candidates.shape)
        predicted = [float(ix*4),float(iy*4)]
        return predicted,float(candidates[iy,ix]),heat


def tensor(pixels,device):
    return torch.from_numpy(np.ascontiguousarray(pixels)).float().div(255)[None,None].to(device)


def make_model(config):
    if config["model"] != "metric_patch_v1":
        raise ValueError("Unknown model")
    return MetricPatch(config["embedding_dim"])
