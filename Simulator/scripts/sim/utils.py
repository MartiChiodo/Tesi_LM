def sample_sku(gen, N):
    """
    Sample a SKU index from a truncated normal distribution over [0, N).

    Draws from a normal distribution centered at N/2 with std N/6,
    rejecting samples outside [0, N) until a valid index is obtained.

    Parameters
    ----------
    gen : numpy.random.Generator   RNG instance.
    N : int                        Total number of SKUs.

    Returns
    -------
    int  A valid SKU index in [0, N).
    """
    while True:
        id_s = int(gen.normal(0.5 * N, N/6))
        if 0 <= id_s < N:
            return id_s
        

