from collections import OrderedDict
from torch import nn
import torch
import copy


class InnerLoop(nn.Module):
    '''
    This module performs the inner loop
    The forward method updates weights with gradient steps on training data, 
    then computes and returns a meta-gradient w.r.t. validation data
    '''
    def __init__(self, network, num_updates, step_size, meta_batch_size):
        super(InnerLoop, self).__init__()
        self.network = copy.deepcopy(network)
        # Number of updates to be taken
        self.num_updates = num_updates
        # Step size for the updates
        self.step_size = step_size
        self.meta_batch_size = meta_batch_size
        self.mse_loss = nn.MSELoss(reduction="mean")

    def copy_weights(self, net):
        ''' Set this module's weights to be the same as those of 'net' '''
        self.network.copy_weights(net)

    def net_forward(self, x, weights=None):
        return self.network.net_forward(x, weights)

    def forward_pass(self, images, target_logits, weights=None):
        ''' Run data through net, return loss and output '''
        images = images.cuda()
        target_logits = target_logits.cuda()
        logits = self.net_forward(images, weights)
        loss = self.mse_loss(logits, target_logits)
        return loss


    def forward(self, task_support_images, task_query_images, task_support_target, task_query_target):
        fast_weights = OrderedDict((name, param) for (name, param) in self.network.named_parameters())
        for i in range(self.num_updates):
            if i==0:
                loss = self.forward_pass(task_support_images, task_support_target)
                grads = torch.autograd.grad(loss, self.parameters())
            else:
                loss = self.forward_pass(task_support_images, task_support_target, fast_weights)
                grads = torch.autograd.grad(loss, fast_weights.values())
            fast_weights = OrderedDict((name, param - self.step_size * grad)
                                     for ((name, param), grad) in zip(fast_weights.items(), grads))
        # Compute the meta gradient and return it
        loss = self.forward_pass(task_query_images, task_query_target, fast_weights)
        loss = loss / self.meta_batch_size   # normalize loss
        grads = torch.autograd.grad(loss, self.parameters())
        meta_grads = {name:g for ((name, _), g) in zip(self.named_parameters(), grads)}
        return meta_grads #, accuracy, mse_error

