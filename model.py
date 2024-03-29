from __future__ import print_function, division

# pytorch imports
import torch
import torch.nn as nn
import torch.optim as optim
from torch.optim import lr_scheduler
from torch.autograd import Variable
import torchvision
from torchvision import datasets, models, transforms
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms, utils

# image imports
from skimage import io, transform
from PIL import Image

# general imports
import os
import time
from shutil import copyfile
from shutil import rmtree

# data science imports
import pandas as pd
import numpy as np
import csv

import cxp_dataset as CXP
import eval_model as E

use_gpu = torch.cuda.is_available()
gpu_count = torch.cuda.device_count()
print("Available GPU count:" + str(gpu_count))


def checkpoint(model, last_train_loss, best_val_acc, metric, epoch, best_epoch, LR, WD):
    """
    Saves checkpoint of torchvision model during training.

    Args:
        model: torchvision model to be saved
        best_loss: best val loss achieved so far in training
        epoch: current epoch of training
        LR: current learning rate in training
    Returns:
        None
    """
    
    state = {
        'model': model,
        'last_train_loss': last_train_loss,
        'best_val_acc': best_val_acc,
        'metric': metric,
        'epoch': epoch,
        'best_epoch': best_epoch,
        'rng_state': torch.get_rng_state(),
        'LR': LR,
        'WD': WD,
    }

    torch.save(state, 'results/checkpoint_' + str(epoch))


def train_model(
        model,
        criterion,
        optimizer,
        LR,
        num_epochs,
        dataloaders,
        dataset_sizes,
        weight_decay,
        dataset,
        data_transforms,
        PATH_TO_IMAGES,
        PATH_TO_CSV,
        val_on_dataset=False):
    """
    Fine tunes torchvision model to CheXpert data.

    Args:
        model: torchvision model to be finetuned (densenet-121 in this case)
        criterion: loss criterion (binary cross entropy loss, BCELoss)
        optimizer: optimizer to use in training (Adam)
        LR: learning rate
        num_epochs: continue training up to this many epochs
        dataloaders: pytorch train and val dataloaders
        dataset_sizes: length of train and val datasets
        weight_decay: weight decay parameter we use in SGD with momentum
    Returns:
        model: trained torchvision model
        best_epoch: epoch on which best model val loss was obtained

    """
    since = time.time()
    

    start_epoch = 1
    best_loss = 999999
    best_val_acc = 0
    best_epoch = -1
    last_train_loss = -1
    last_val_acc = 0
    
    if val_on_dataset:
        print("WARNING: VALIDATING ON DATASET")
        with open("results/logger", 'a') as logfile:
            logfile.write("WARNING: VALIDATING ON DATASET\n")
            
    print(time.strftime("%d %b %Y %H:%M:%S", time.gmtime(time.time()-25200)))
    with open("results/logger", 'a') as logfile:
        logfile.write(time.strftime("%d %b %Y %H:%M:%S\n", time.gmtime(time.time()-25200)))

    # iterate over epochs
    for epoch in range(start_epoch, num_epochs + 1):
        print('Epoch {}/{}'.format(epoch, num_epochs))
        print('-' * 10)
        
        with open("results/logger", 'a') as logfile:
            logfile.write('Epoch {}/{}\n'.format(epoch, num_epochs))
            logfile.write('-' * 10 + '\n')

        running_loss = 0.0
        running_misclass = 0

        i = 0
        total_done = 0
        
        model.train(True)
        print("Model train: ", model.training)

        # iterate over all data in train/val dataloader:
        for data in dataloaders['train']:
            i += 1
            inputs, labels, _ = data
            #print(labels)
            batch_size = inputs.shape[0]
            inputs = Variable(inputs.cuda())
            if str(criterion) == str(nn.BCELoss()):
                labels = Variable(labels.cuda()).float()
            else:
                labels = Variable(labels.cuda()).long()
            outputs = model(inputs)

            # calculate gradient and update parameters in train phase
            optimizer.zero_grad()
            loss = criterion(outputs, labels)
            
            loss.backward()
            optimizer.step()

            running_loss += loss.data.item() * batch_size

            #if phase == 'val' and str(criterion) == str(nn.CrossEntropyLoss()):
            #    print(labels)
            #    idx = torch.argmax(outputs, dim=1)
            #    print(idx)

        epoch_loss = running_loss / dataset_sizes['train']

        print(time.strftime("%d %b %Y %H:%M:%S", time.gmtime(time.time()-25200)))
        with open("results/logger", 'a') as logfile:
            logfile.write(time.strftime("%d %b %Y %H:%M:%S\n", time.gmtime(time.time()-25200)))

        print('train epoch {}: loss {:.4f} with data size {}'.format(
            epoch, epoch_loss, dataset_sizes['train']))
        with open("results/logger", 'a') as logfile:
            logfile.write('train epoch {}: loss {:.4f} with data size {}\n'.format(
            epoch, epoch_loss, dataset_sizes['train']))

        time_elapsed = time.time() - since
        print('train epoch complete in {:.0f}m {:.0f}s'.format(
            time_elapsed // 60, time_elapsed % 60))
        with open("results/logger", 'a') as logfile:
            logfile.write('train epoch complete in {:.0f}m {:.0f}s\n'.format(
            time_elapsed // 60, time_elapsed % 60))

        last_train_loss = epoch_loss
        
        # keep track of best train loss
        if epoch_loss < best_loss:
            best_loss = epoch_loss
            
        # done with training

        if str(criterion) == 'BCELoss()':
            if val_on_dataset:
                _, metric = E.make_pred_multilabel(data_transforms, model, 
                                                   PATH_TO_IMAGES, PATH_TO_CSV, 'auc', dataset=dataset)
            else:
                _, metric = E.make_pred_multilabel(data_transforms, model, 
                                                   PATH_TO_IMAGES, PATH_TO_CSV, 'auc')
        else:
            _, metric = E.make_pred_multilabel(data_transforms, model, 
                                                   PATH_TO_IMAGES, PATH_TO_CSV, 'auc', dataset=dataset, multiclass=True)

        auc = metric.as_matrix(columns=metric.columns[1:])
        last_val_acc = auc[~np.isnan(auc)].mean() 

        print(metric)
        with open("results/logger", 'a') as logfile:
            print(metric, file=logfile)

        print('mean epoch validation accuracy:', last_val_acc)
        with open("results/logger", 'a') as logfile:
            logfile.write('mean epoch validation accuracy: ' + str(last_val_acc) + '\n')
                
        # decay learning rate if no val accuracy improvement in this epoch
        if last_val_acc < best_val_acc: 
            print("Running with LR decay on val accuracy")
            with open("results/logger", 'a') as logfile:
                logfile.write("Running with LR decay on val accuracy\n")
            print("decay loss from " + str(LR) + " to " +
                  str(LR / 10) + " as not seeing improvement in val accuracy")
            with open("results/logger", 'a') as logfile:
                logfile.write("decay loss from " + str(LR) + " to " +
                  str(LR / 10) + " as not seeing improvement in val accuracy\n")
            LR = LR / 10
            optimizer = optim.Adam(
                filter(
                    lambda p: p.requires_grad,
                    model.parameters()),
                lr=LR,
                betas=(0.9, 0.999),
                eps=1e-08,
                weight_decay=weight_decay)

            print("created new optimizer with LR " + str(LR))
            with open("results/logger", 'a') as logfile:
                    logfile.write("created new optimizer with LR " + str(LR) + '\n')


        # track best val accuracy yet
        if last_val_acc > best_val_acc:
            best_val_acc = last_val_acc
            best_epoch = epoch

        print('saving checkpoint_' + str(epoch))
        with open("results/logger", 'a') as logfile:
            logfile.write('saving checkpoint_' + str(epoch) + '\n')
        checkpoint(model, last_train_loss, last_val_acc, metric, epoch, best_epoch, LR, weight_decay)

        # log training loss over each epoch
        with open("results/log_train", 'a') as logfile:
            logwriter = csv.writer(logfile, delimiter=',')
            if(epoch == 1):
                logwriter.writerow(["epoch", "train_loss", "average auc"])
            logwriter.writerow([epoch, last_train_loss, last_val_acc])

        print("best epoch: ", best_epoch)
        with open("results/logger", 'a') as logfile:
            logfile.write("best epoch: " + str(best_epoch) + '\n')
                    
        print("best train loss: ", best_loss)
        with open("results/logger", 'a') as logfile:
            logfile.write("best train loss: " + str(best_loss) + '\n')
        
        print("best val accuracy: ", best_val_acc)
        with open("results/logger", 'a') as logfile:
            logfile.write("best val accuracy: " + str(best_val_acc) + '\n')
                    
        total_done += batch_size
        if(total_done % (100 * batch_size) == 0):
            print("completed " + str(total_done) + " so far in epoch")
            with open("results/logger", 'a') as logfile:
                logfile.write("completed " + str(total_done) + " so far in epoch\n")

        # break if no val loss improvement in 3 epochs
        if ((epoch - best_epoch) >= 3):
            print("no improvement in 3 epochs, break")
            with open("results/logger", 'a') as logfile:
                logfile.write("no improvement in 3 epochs, break\n")
            break

    time_elapsed = time.time() - since
    print('Training complete in {:.0f}m {:.0f}s'.format(
        time_elapsed // 60, time_elapsed % 60))
    with open("results/logger", 'a') as logfile:
        logfile.write('Training complete in {:.0f}m {:.0f}s\n'.format(
        time_elapsed // 60, time_elapsed % 60))

    # load best model weights to return
    checkpoint_best = torch.load('results/checkpoint_' + str(best_epoch))
    model = checkpoint_best['model']

    return model, best_epoch


def train_cnn(PATH_TO_IMAGES, PATH_TO_CSV, LR, WEIGHT_DECAY, orientation='all', cross_val_on_train=False, 
              NUM_IMAGES=223414, PATH_TO_CHECKPOINT=None):
    """
    Train torchvision model to NIH data given high level hyperparameters.

    Args:
        PATH_TO_IMAGES: path to NIH images
        LR: learning rate
        WEIGHT_DECAY: weight decay parameter for SGD

    Returns:
        preds: torchvision model predictions on test fold with ground truth for comparison
        aucs: AUCs for each train,test tuple

    """
    
    if orientation not in ['all', 'ap', 'pa', 'lat', 'trainer']:
        print('Not using a valid orientation')
        return
    
    try:
        if os.path.exists('results/'):
            print("Remove or rename results directory")
            return
        else:
            rmtree('results/')
    except BaseException:
        pass  # directory doesn't yet exist, no need to clear it
    os.makedirs("results/")
    
    
    NUM_EPOCHS = 100
    BATCH_SIZE = 16
    
    print("Running with WD, LR:", WEIGHT_DECAY, LR)
    print("Using orientation:", orientation)
    
    with open("results/logger", 'a') as logfile:
        logfile.write("Running with WD, LR: " + str(WEIGHT_DECAY) + ' ' + str(LR) + '\n')
        logfile.write("Using orientation: " + orientation + '\n')

    # use imagenet mean,std for normalization
    mean = [0.485, 0.456, 0.406]
    std = [0.229, 0.224, 0.225]

    N_LABELS = 5  # we are predicting 5 labels
    N_ORIENTS = 3 # we are predicting 3 orientations
    
    
    # define torchvision transforms
    data_transforms = {
        'val': transforms.Compose([
            transforms.Resize(224),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(mean, std)
        ]),
    }
    
    if orientation == 'all':
        data_transforms['train'] = transforms.Compose([
            transforms.RandomHorizontalFlip(),
            transforms.Resize(224), # changed for pytorch 4.0.1
            # because scale doesn't always give 224 x 224, this ensures 224 x
            # 224
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(mean, std)
        ])
        print("Using random horizontal flip")
        with open("results/logger", 'a') as logfile:
            logfile.write("Using random horizontal flip\n")
    else:
        data_transforms['train'] = transforms.Compose([
            #transforms.RandomHorizontalFlip(),
            transforms.Resize(224), # changed for pytorch 4.0.1
            # because scale doesn't always give 224 x 224, this ensures 224 x
            # 224
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(mean, std)
        ])
        print("Not using random horizontal flip")
        with open("results/logger", 'a') as logfile:
            logfile.write("Not using random horizontal flip\n")
    
    print(data_transforms)

    # create train/val dataloaders
    transformed_datasets = {}
    
    if cross_val_on_train == False: 
        print("Not cross validating on train set")
        with open("results/logger", 'a') as logfile:
            logfile.write("Not cross validating on train set\n")
        print("On train: ", end=" ")
        with open("results/logger", 'a') as logfile:
            logfile.write("On train: ")
        transformed_datasets['train'] = CXP.CXPDataset(
            path_to_images=PATH_TO_IMAGES,
            path_to_csv=PATH_TO_CSV,
            fold='train',
            uncertain = 'ones',
            transform=data_transforms['train'],
            orientation=orientation,
            sample = NUM_IMAGES,
            verbose = True
        )
        print("On val: ", end=" ")
        with open("results/logger", 'a') as logfile:
            logfile.write("On val: ")
        transformed_datasets['val'] = CXP.CXPDataset(
            path_to_images=PATH_TO_IMAGES,
            path_to_csv=PATH_TO_CSV,
            fold='val',
            transform=data_transforms['val'],
            orientation=orientation,
            verbose = True
        )
    else:
        mask = np.random.rand(NUM_IMAGES) < .8
        #print(mask)
        #print(~mask)
        
        print("Cross validating on train set")
        with open("results/logger", 'a') as logfile:
            logfile.write("Cross validating on train set\n")
        print("On train: ", end=" ")
        with open("results/logger", 'a') as logfile:
            logfile.write("On train: ")
        HEAD = 0.8
        transformed_datasets['train'] = CXP.CXPDataset(
            path_to_images=PATH_TO_IMAGES,
            path_to_csv=PATH_TO_CSV,
            fold='train',
            uncertain = 'ones',
            transform=data_transforms['train'],
            orientation=orientation,
            sample = NUM_IMAGES,
            mask = mask,
            verbose = True
        )
        print("On val: ", end=" ")
        with open("results/logger", 'a') as logfile:
            logfile.write("On val: ")
        transformed_datasets['val'] = CXP.CXPDataset(
            path_to_images=PATH_TO_IMAGES,
            path_to_csv=PATH_TO_CSV,
            fold='train',
            uncertain = 'ones',
            transform=data_transforms['val'],
            orientation=orientation,
            sample = NUM_IMAGES,
            mask = ~mask,
            verbose = True
        )
        
    #print(transformed_datasets['train'].df[transformed_datasets['train'].df.columns[0]])
    #print(transformed_datasets['val'].df[transformed_datasets['val'].df.columns[0]])
    
    #print("Size of train set:", len(transformed_datasets['train']))
    #print("Size of val set:", len(transformed_datasets['val']))

    dataloaders = {}
    dataloaders['train'] = torch.utils.data.DataLoader(
        transformed_datasets['train'],
        batch_size=BATCH_SIZE,
        shuffle=True,
        num_workers=8)
    dataloaders['val'] = torch.utils.data.DataLoader(
        transformed_datasets['val'],
        batch_size=BATCH_SIZE,
        shuffle=True,
        num_workers=8)

    # please do not attempt to train without GPU as will take excessively long
    if not use_gpu:
        raise ValueError("Error, requires GPU")
        
    if PATH_TO_CHECKPOINT == None:
        model = models.densenet121(pretrained=True)
        num_ftrs = model.classifier.in_features
        # add final layer with # outputs in same dimension of labels with sigmoid
        # activation
        if orientation != 'trainer':
            model.classifier = nn.Sequential(
                nn.Linear(num_ftrs, N_LABELS), nn.Sigmoid())
        else:
            model.classifier = nn.Sequential(
                nn.Linear(num_ftrs, N_ORIENTS), nn.Softmax())

        # put model on GPU
        model = model.cuda()
    else:
        checkpoint = torch.load(PATH_TO_CHECKPOINT)
        model = checkpoint['model']

    # define criterion, optimizer for training
    if orientation != 'trainer':
        criterion = nn.BCELoss()
    else:
        criterion = nn.CrossEntropyLoss()
        
    print(criterion)
    
    optimizer = optim.Adam(
        filter(
            lambda p: p.requires_grad,
            model.parameters()),
        lr=LR,
        betas=(0.9, 0.999),
        eps=1e-08,
        weight_decay=WEIGHT_DECAY,
    )
    dataset_sizes = {x: len(transformed_datasets[x]) for x in ['train', 'val']}
    
    print("Model training start")

    # train model
    model, best_epoch = train_model(model, criterion, optimizer, LR, num_epochs=NUM_EPOCHS,
                                    dataloaders=dataloaders, dataset_sizes=dataset_sizes, weight_decay=WEIGHT_DECAY, 
                                    dataset=transformed_datasets['val'], data_transforms=data_transforms, 
                                    PATH_TO_IMAGES=PATH_TO_IMAGES, PATH_TO_CSV=PATH_TO_CSV, val_on_dataset=cross_val_on_train)
    
    print("Model training complete")

    # get preds and AUCs on test fold
    #preds, aucs = E.make_pred_multilabel(
    #    data_transforms, model, PATH_TO_IMAGES, PATH_TO_CSV, 'auc')

    #return preds, aucs
