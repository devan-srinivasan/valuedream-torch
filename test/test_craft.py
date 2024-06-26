import wandb
import argparse
import os
import torch
import numpy as np
import gym
import sys
sys.path.append("/home/leesophie99/projects/dreamerprojs/dreamerv2")
# sys.path.append("/home/leesophie99/miniconda3/envs/dreamer_raj/lib/python3.9/site-packages/crafter")
from dreamerv2.utils.wrapper import OneHotAction
from dreamerv2.training.config import CrafterConfig
from dreamerv2.training.trainer import Trainer
from dreamerv2.training.evaluator import Evaluator

import crafter

# from gym import envs
# all_envs = envs.registry.all()
# env_ids = [env_spec.id for env_spec in all_envs if "cr" in env_spec.id]
# print(sorted(env_ids))
# env = gym.make("CrafterNoReward-v1")#"CrafterReward-v1")

def main(args):
    wandb.login()
    env_name = args.env
    exp_id = args.id + '_craftertest'

    '''make dir for saving results'''
    result_dir = os.path.join('results', '{}_{}'.format(env_name, exp_id))
    model_dir = os.path.join(result_dir, 'models')                                                  #dir to save learnt models
    os.makedirs(model_dir, exist_ok=True)

    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available() and args.device:
        device = torch.device('cuda')
        torch.cuda.manual_seed(args.seed)
    else:
        device = torch.device('cpu')
    print('using :', device)  

    env = gym.make('CrafterReward-v1')
    # action_size = env.action_space.shape[0]
    action_size = (env.action_space.n)

    config = CrafterConfig(env='CrafterReward-v1', obs_shape=(64,64,3), action_size=action_size)

    config_dict = config.__dict__
    trainer = Trainer(config, device)
    evaluator = Evaluator(config, device)
    
    with wandb.init(project='dreamer crafter test', config=config_dict):
        """training loop"""
        print('...training...')
        train_metrics = {}
        trainer.collect_seed_episodes(env)
        obs, score = env.reset(), 0
        done = False
        prev_rssmstate = trainer.RSSM._init_rssm_state(1)
        prev_action = torch.zeros(1, trainer.action_size).to(trainer.device)
        episode_actor_ent = []
        scores = []
        best_mean_score = 0
        train_episodes = 0
        best_save_path = os.path.join(model_dir, 'models_best.pth')
        for iter in range(1, trainer.config.train_steps):  
            if iter%trainer.config.train_every == 0:
                train_metrics = trainer.train_batch(train_metrics)
            if iter%trainer.config.slow_target_update == 0:
                trainer.update_target()                
            if iter%trainer.config.save_every == 0:
                trainer.save_model(iter)
            with torch.no_grad():
                embed = trainer.ObsEncoder(torch.tensor(obs, dtype=torch.float32).unsqueeze(0).to(trainer.device))  
                _, posterior_rssm_state = trainer.RSSM.rssm_observe(embed, prev_action, not done, prev_rssmstate)
                model_state = trainer.RSSM.get_model_state(posterior_rssm_state)
                action, action_dist = trainer.ActionModel(model_state)
                action = trainer.ActionModel.add_exploration(action, iter).detach()
                action_ent = torch.mean(action_dist.entropy()).item()
                episode_actor_ent.append(action_ent)

            next_obs, rew, done, _ = env.step(action.squeeze(0).cpu().numpy())
            score += rew

            if done:
                train_episodes += 1
                trainer.buffer.add(obs, action.squeeze(0).cpu().numpy(), rew, done)
                train_metrics['train_rewards'] = score
                train_metrics['action_ent'] =  np.mean(episode_actor_ent)
                train_metrics['train_steps'] = iter
                wandb.log(train_metrics, step=train_episodes)
                scores.append(score)
                if len(scores)>100:
                    scores.pop(0)
                    current_average = np.mean(scores)
                    if current_average>best_mean_score:
                        best_mean_score = current_average 
                        print('saving best model with mean score : ', best_mean_score)
                        save_dict = trainer.get_save_dict()
                        torch.save(save_dict, best_save_path)
                
                obs, score = env.reset(), 0
                done = False
                prev_rssmstate = trainer.RSSM._init_rssm_state(1)
                prev_action = torch.zeros(1, trainer.action_size).to(trainer.device)
                episode_actor_ent = []
            else:
                trainer.buffer.add(obs, action.squeeze(0).detach().cpu().numpy(), rew, done)
                obs = next_obs
                prev_rssmstate = posterior_rssm_state
                prev_action = action

    '''evaluating probably best model'''
    evaluator.eval_saved_agent(env, best_save_path)

if __name__ == "__main__":

    """there are tonnes of HPs, if you want to do an ablation over any particular one, please add if here"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default='crafter', type=str, help='mini atari env name')
    parser.add_argument("--id", type=str, default='0', help='Experiment ID')
    parser.add_argument('--seed', type=int, default=123, help='Random seed')
    parser.add_argument('--device', default='cuda', help='CUDA or CPU')
    parser.add_argument('--batch_size', type=int, default=50, help='Batch size')
    parser.add_argument('--seq_len', type=int, default=50, help='Sequence Length (chunk length)')
    args = parser.parse_args()
    main(args)