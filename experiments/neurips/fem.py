from dpsynth.mechanisms import DualQuery, FEM
from mbi import Dataset, CliqueVector, FactoredInference, RegionGraph, FactorGraph
import itertools
import numpy as np
import argparse
import os
import pandas as pd
from mbi.optimization import Optimizer

def default_params():
    """
    Return default parameters to run this program

    :returns: a dictionary of default parameter settings for each command line argument
    """
    params = {}
    params['iters'] = 50
    params['epsilon'] = 1.0
    params['seed'] = 0
    params['save'] = None

    return params

if __name__ == '__main__':
    description = ''
    formatter = argparse.ArgumentDefaultsHelpFormatter
    parser = argparse.ArgumentParser(description=description, formatter_class=formatter)
    parser.add_argument('--iters', type=int, help='number of optimization iterations')
    parser.add_argument('--epsilon', type=float, help='privacy  parameter')
    parser.add_argument('--seed', type=int, help='random seed')
    parser.add_argument('--save', type=str, help='path to save results')

    parser.set_defaults(**default_params())
    args = parser.parse_args()

    prng = np.random.RandomState(args.seed)
    prefix = os.getenv('HD_DATA') #'/home/rmckenna/Repos/hd-datasets/clean/'

    name = 'adult'
    data = Dataset.load(prefix+name+'.csv', prefix+name+'-domain.json')

    total = data.records
    delta = 1.0/total**2
    all3way = list(itertools.combinations(data.domain, 3))
    proj = [p for p in all3way if data.domain.size(p) <= total]
    cliques = [proj[i] for i in prng.choice(len(proj), 64, replace=False)]

    W = [(cl, None) for cl in cliques]

    mech = FEM(args.epsilon, delta, prng, noise_multiple=0.16, epsilon_split=0.008, samples=50)
    synth = mech.run(data, W)

    oracle = RegionGraph(data.domain, cliques, total=1.0,minimal=True, convex=True, iters=1)
    marginals = CliqueVector.from_data(synth, oracle.regions)*(1.0/synth.records)
    #marginals = CliqueVector.from_data(data, oracle.regions)*(1.0/data.records)
    oracle.potentials = oracle.mle(marginals)
    for _ in range(100):
        oracle.marginals = oracle.belief_propagation(oracle.potentials)

    #from IPython import embed; embed()
    #oracle = 'convex'
    engine = FactoredInference(data.domain, 
                            log=False,
                            iters=args.iters,
                            warm_start=False,
                            marginal_oracle=oracle, 
                            metric=mech._marginal_loss)

    measurements = [(None, None, 1.0, cl) for cl in cliques]

    def cb(mu):
        PGM_L1 = 0
        PGM_Linf = 0

        for cl in cliques:
            x = data.project(cl).datavector()
            for r in mu:
                if set(cl) <= set(r):
                    z = mu[r].project(cl).datavector()
                    break
            x /= x.sum()
            z /= z.sum()
            PGM_L1 += np.linalg.norm(x-z,1)
            PGM_Linf = max(PGM_Linf, np.linalg.norm(x-z,np.inf))

        print(PGM_Linf, PGM_L1/2/len(cliques), flush=True)

    #opt = Optimizer(data.domain, cliques, total=data.records)
    #mu = opt.estimate(measurements, data.records, callback=cb, backend='scipy', metric=mech._marginal_loss)

    #from IPython import embed; embed()
    #print(cb(marginals))

    print('starting optimization...')        

    stepsizes = {}
    stepsizes[0.1] = 10
    stepsizes[0.15] = 10
    stepsizes[0.2] = 5
    stepsizes[0.25] = 5
    stepsizes[0.5] = 2
    stepsizes[1.0] = 2

    opts = {'stepsize':stepsizes[args.epsilon]}
    #model = engine.estimate(measurements, total=data.records, engine='MD3', options={},callback=cb)
    model = engine.estimate(measurements, total=data.records, engine='MD', options=opts,callback=cb) 

    results = vars(args)
    path = results.pop('save')
    FEM_L1 = 0
    FEM_Linf = 0
    PGM_L1 = 0
    PGM_Linf = 0

    for cl in cliques:
        x = data.project(cl).datavector()
        y = synth.project(cl).datavector()
        z = model.project(cl).datavector()
        x /= x.sum()
        y /= y.sum()
        z /= z.sum()
        FEM_L1 += np.linalg.norm(x-y,1)
        PGM_L1 += np.linalg.norm(x-z,1)
        FEM_Linf = max(FEM_Linf, np.linalg.norm(x-y,np.inf))
        PGM_Linf = max(PGM_Linf, np.linalg.norm(x-z,np.inf))

    results['FEM_L1'] = FEM_L1 / 2 / len(cliques)
    results['PGM_L1'] = PGM_L1 / 2 / len(cliques)
    results['FEM_Linf'] = FEM_Linf
    results['PGM_Linf'] = PGM_Linf
    results = pd.DataFrame(results, index=[0])

    if path is None:
        print(results)
    else:
        with open(path, 'a') as f:
            results.to_csv(f, mode='a', index=False, header=f.tell()==0)

