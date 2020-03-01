import argparse
import sys
sys.path.append("/home1/machen/meta_perturbations_black_box_attack")
import os
import random
import glog as log
import numpy as np
import torch
from torch.utils.data import DataLoader

from config import MODELS_TRAIN_STANDARD, PY_ROOT
from dataset.model_constructor import StandardModel
from meta_grad_attacker.dataset.image_gradient_dataset import ImageGradientDataset
from meta_grad_attacker.meta_training.meta import Meta
def set_log_file(fname):
    import subprocess
    tee = subprocess.Popen(['tee', fname], stdin=subprocess.PIPE)
    os.dup2(tee.stdin.fileno(), sys.stdout.fileno())
    os.dup2(tee.stdin.fileno(), sys.stderr.fileno())



def get_parse_args():
    argparser = argparse.ArgumentParser()
    argparser.add_argument('--epoch', type=int, help='epoch number', default=20)
    argparser.add_argument("--dataset", type=str, choices=["CIFAR-10","CIFAR-100","TinyImageNet", "ImageNet"])
    argparser.add_argument('--k_spt', type=int, help='k shot for support set', default=10)
    argparser.add_argument('--k_qry', type=int, help='k shot for query set', default=10)
    # argparser.add_argument('--imgsz', type=int, help='imgsz', default=64)
    argparser.add_argument('--batchsize', type=int, help='batchsize', default=64)
    argparser.add_argument('--task_num', type=int, help='meta batch size, namely task num', default=3)
    argparser.add_argument('--meta_lr', type=float, help='meta-level outer learning rate', default=1e-2)
    argparser.add_argument('--update_lr', type=float, help='task-level inner update learning rate', default=1e-2)
    argparser.add_argument('--update_step', type=int, help='task-level inner update steps', default=5)
    argparser.add_argument('--update_step_test', type=int, help='update steps for finetunning', default=20)
    argparser.add_argument("--gpu", type=int, required=True)

    args = argparser.parse_args()
    os.environ['CUDA_VISIBLE_DEVICES'] = str(args.gpu)
    return args

def main(args):
    config = [
        ('conv2d', [32, 3, 3, 3, 1, 1]),
        ('relu', [True]),
        ('bn', [32]),
        ('conv2d', [64, 32, 4, 4, 2, 1]),
        ('relu', [True]),
        ('bn', [64]),
        ('conv2d', [128, 64, 4, 4, 2, 1]),
        ('relu', [True]),
        ('bn', [128]),
        ('conv2d', [256, 128, 4, 4, 2, 1]),
        ('relu', [True]),
        ('bn', [256]),
        ('convt2d', [256, 128, 4, 4, 2, 1]),
        ('relu', [True]),
        ('bn', [128]),
        ('convt2d', [128, 64, 4, 4, 2, 1]),
        ('relu', [True]),
        ('bn', [64]),
        ('convt2d', [64, 32, 4, 4, 2, 1]),
        ('relu', [True]),
        ('bn', [32]),
        ('convt2d', [32, 3, 3, 3, 1, 1]),
    ]

    maml = Meta(args, config).cuda()
    # initiate different datasets
    minis = []
    archs = MODELS_TRAIN_STANDARD[args.dataset]
    for arch in archs:
        root_path = "{}/data_grad_regression/{}/".format(PY_ROOT, args.dataset)
        mini = ImageGradientDataset(root_path, arch, args.dataset, k_shot=args.k_spt, k_query=args.k_qry)
        db = DataLoader(mini, args.batchsize, shuffle=True, num_workers=0, pin_memory=True)
        minis.append(db)

    if args.dataset == "ImageNet":
        arch_test = "vgg19_bn"
    elif args.dataset.startswith("CIFAR"):
        arch_test = "resnext-16x64d"
    elif args.dataset == "TinyImageNet":
        arch_test = "densenet201"

    root_test =  "{}/data_grad_regression/{}/".format(PY_ROOT, args.dataset)
    mini_test = ImageGradientDataset(root_test, arch_test, args.dataset,
                                  k_shot=args.k_spt, k_query=args.k_qry)
    mini_test = DataLoader(mini_test, 10, shuffle=True, num_workers=0, pin_memory=True)
    # start training
    step_number = len(minis[0])
    BEST_ACC = 1.5
    target_model = StandardModel(args.dataset, arch_test, no_grad=True).eval().cuda()
    log_file_path = '{}/train_pytorch_model/meta_grad_regression/train_{}.log'.format(PY_ROOT, args.dataset)
    set_log_file(log_file_path)

    def save_model(model, dataset, epoch, acc):
        model_folder_path = '{}/train_pytorch_model/meta_grad_regression'.format(PY_ROOT)
        os.makedirs(model_folder_path, exist_ok=True)
        file_name =  dataset  + '.pth.tar'
        save_model_path = os.path.join(model_folder_path, file_name)
        torch.save({"state_dict": model.state_dict(), "accuracy": acc, "epoch":epoch}, save_model_path)

    for epoch in range(args.epoch):
        minis_iter = []
        for i in range(len(minis)):
            minis_iter.append(iter(minis[i]))
        mini_test_iter = iter(mini_test)
        for step in range(step_number):
            batch_data = []
            for task_idx in range(args.task_num):
                each_iter = random.choice(minis_iter)
                batch_data.append(each_iter.next())
            accs = maml(batch_data)
            if (step + 1) % step_number == 0:
                log.info('step: {}  training acc: {:.6f}'.format(step, accs[0].item()))
                if accs[0].item() < BEST_ACC:
                    BEST_ACC = accs[0].item()
                    save_model(maml, args.dataset, epoch, BEST_ACC)
            if (epoch + 1) % (15) == 0 and step == 0:  # evaluation
                accs_all_test = []
                for i in range(3):
                    test_data = mini_test_iter.next()
                    accs = maml.finetunning(test_data, target_model)
                    accs_all_test.append(accs)
                accs = np.array(accs_all_test).mean(axis=0).astype(np.float16)
                log.info('Test acc:', accs)

if __name__ == "__main__":
    args = get_parse_args()
    main(args)