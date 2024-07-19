# -*- coding: utf-8 -*-
'''

Train CIFAR10 with PyTorch and Vision Transformers!
written by @kentaroy47, @arutema47

'''

from __future__ import print_function

import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
import torch.backends.cudnn as cudnn
import numpy as np

import torchvision
import torchvision.transforms as transforms

import os
from types import SimpleNamespace
import pandas as pds
import csv
import time

from utils import progress_bar, load_data, load_model, train, test
from randomaug import RandAugment


default_args = dict(
    lr = 1e-4,
    opt = "adam",
    resume = False,
    aug = True,
    mp_dtype = "bf16",
    wandb = True,
    mixup = True,
    net = "vit",
    bs = 512,
    size = 32,
    n_epochs = 100,
    patch = 4,
    dim = 64,
    convkernel = 8,
    num_classes=10,

    mlp_dim = 1024,
    compile=False,
    acts = ["gelu", "gelu", "gelu", "gelu", "gelu", "gelu"],
    # acts = ["sign_gelu2", "sign_gelu2", "sign_gelu2", "sign_gelu2", "sign_gelu2", "sign_gelu2"],
    # acts = ["sinlu", "sinlu", "sinlu", "sinlu", "sinlu", "sinlu"],
    act_powers = [1, 1, 1, 1, 1, 1],
    # act_powers = [2, 2, 2, 2, 2, 2],
    val_act = None,
    post_attn_act = None,
    attn_power = 1.0,
    # post_attn_act = "gelu",
)


def train_model(args):
    def loss_fn(net_fwd, inputs, targets):
        pred_labels = net_forward(inputs)
        loss = nn.CrossEntropyLoss()(pred_labels, targets)
        return loss, pred_labels


    args = SimpleNamespace(**args)
    args.device = 'cuda' if torch.cuda.is_available() else 'cpu'
    args.best_acc = 0  # best test accuracy
    args.start_epoch = 0  # start from epoch 0 or last checkpoint epoch

    trainloader, testloader = load_data(args)
    net, net_forward = load_model(args)

    print("NUM PARAMS: ", sum([p.numel() for p in net.parameters()]))

    if args.resume:
        # Load checkpoint.
        print('==> Resuming from checkpoint..')
        assert os.path.isdir('checkpoint'), 'Error: no checkpoint directory found!'
        checkpoint = torch.load('./checkpoint/{}-ckpt.t7'.format(args.net))
        net.load_state_dict(checkpoint['net'])
        args.best_acc = checkpoint['acc']
        args.start_epoch = checkpoint['epoch']

    optimizer = optim.AdamW(net.parameters(), lr=args.lr)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, args.n_epochs)

    ##### Training
    scaler = torch.cuda.amp.GradScaler(enabled=args.mp_dtype == "float16")
    list_loss = []
    list_acc = []

    if args.wandb:
        import wandb
        watermark = "run"
        if args.val_act is not None:
            watermark = f"{watermark}_vact_{args.val_act}"
        if args.post_attn_act is not None:
            watermark = f"{watermark}_pact_{args.post_attn_act}"

        if args.attn_power != 1:
            watermark = f"{watermark}_attn_{args.attn_power}"
        
        unique_activations = list(set(args.acts))
        non_gelu = [a for a in unique_activations if a != "gelu"]
        if len(non_gelu) > 0:
            non_gelu = non_gelu[0]
            indices = tuple([i+1 for i, a in enumerate(args.acts) if a == non_gelu])
            watermark = watermark + "_{}-{}".format(non_gelu, indices)

        unique_powers = list(set(args.act_powers))
        non_one = [a for a in unique_powers if a != 1]
        if len(non_one) > 0:
            non_one = non_one[0]
            indices = tuple([i+1 for i, a in enumerate(args.act_powers) if a == non_one])
            watermark = watermark + "_{}-{}".format(non_one, indices)

        wandb.init(project="cifar10-challange", name=watermark)
        wandb.config.update(args)

    if args.wandb:
        wandb.watch(net)
        
    for epoch in range(args.start_epoch, args.n_epochs):
        start = time.time()
        trainloss = train(args, epoch, net, net_forward, trainloader, optimizer, scaler, loss_fn=loss_fn)
        val_loss, acc = test(args, epoch, net, net_forward, testloader, optimizer, scaler)
        
        scheduler.step(epoch-1) # step cosine scheduling
        
        list_loss.append(val_loss)
        list_acc.append(acc)
        
        # Log training..
        if args.wandb:
            wandb.log({'epoch': epoch, 'train_loss': trainloss, 'val_loss': val_loss, "val_acc": acc, "lr": optimizer.param_groups[0]["lr"],
            "epoch_time": time.time()-start})

        # Write out csv..
        with open(f'log/log_{args.net}_patch{args.patch}.csv', 'w') as f:
            writer = csv.writer(f, lineterminator='\n')
            writer.writerow(list_loss) 
            writer.writerow(list_acc) 
        print(list_loss)

    # writeout wandb
    if args.wandb:
        wandb.save("wandb_{}.h5".format(args.net))
        wandb.finish()

if __name__ == '__main__':
    args = default_args
    train_model(args)
    
