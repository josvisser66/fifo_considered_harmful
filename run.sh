#!/bin/bash

# This function runs a series of simulations with different arrival rates
# using either a cancel or no_cancel strategy (meaning that the simulated
# clients will be cancelled or not after their deadlines expire.

function doe {
  for f in 05 10 15 20 40 80; do
    echo $f
    ../simulation.py --arrival_rate=$f --save_fig=fig$f.png $1 >lifo$f.txt
  done
}

# Run a series of simulations with the "cancel" strategy.
echo cancel
pushd cancel
doe ""
popd

# Run a series of simulations with the "no_cancel" strategy.
echo no_cancel
pushd no_cancel
doe "--no_cancel"
popd
