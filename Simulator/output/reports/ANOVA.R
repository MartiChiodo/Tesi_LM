# Carico i pacchetti che servono
library(tidyr)     # per trasformare da wide a long
library(dplyr)     # per manipolare i data frame
library(emmeans)   # per i confronti post hoc


# 1. Leggo i due CSV (formato wide: scenari sulle righe, seed sulle colonne)

path_policy <- "Simulator/output/reports/Opt_False_throughput.csv"
path_opt    <- "Simulator/output/reports/Opt_True_throughput.csv"

policy_wide <- read.csv(path_policy, check.names = FALSE)
opt_wide    <- read.csv(path_opt,    check.names = FALSE)

# check.names = FALSE evita che R aggiunga una "X" davanti ai nomi
# delle colonne che iniziano con un numero (i seed)


# 2. Trasformo da wide a long

# pivot_longer prende le colonne dei seed e le impila in due colonne:
# una con il nome del seed, una con il valore di throughput
policy_long <- pivot_longer(policy_wide,
                            cols = -Scenario,        # tutte le colonne tranne Scenario
                            names_to = "seed",
                            values_to = "thr_policy")

opt_long <- pivot_longer(opt_wide,
                         cols = -Scenario,
                         names_to = "seed",
                         values_to = "thr_opt")


# 3. Appaio le due strategie e calcolo la differenza


# unisco i due data frame facendo combaciare le righe che hanno
# lo stesso Scenario e lo stesso seed
diffs <- merge(policy_long, opt_long, by = c("Scenario", "seed"))

# calcolo la differenza optimizer meno policy
diffs$D <- diffs$thr_opt - diffs$thr_policy

# controllo di avere 120 righe (12 scenari per 10 seed)
nrow(diffs)


# 4. Ricavo i tre fattori dall'ID dello scenario


# prima cifra dell'ID: 1 = small, 3 = medium, 5 = large
diffs$d1 <- diffs$Scenario %/% 10     # divisione intera per 10
diffs$d2 <- diffs$Scenario %% 10      # resto della divisione per 10

# warehouse dalla prima cifra
diffs$warehouse <- NA
diffs$warehouse[diffs$d1 == 1] <- "small"
diffs$warehouse[diffs$d1 == 3] <- "medium"
diffs$warehouse[diffs$d1 == 5] <- "large"

# order composition dalla seconda cifra (dispari = small, pari = large)
diffs$composition <- NA
diffs$composition[diffs$d2 %% 2 == 1] <- "small"
diffs$composition[diffs$d2 %% 2 == 0] <- "large"

# arrival rate dalla seconda cifra (1 e 2 = low, 3 e 4 = high)
diffs$arrival <- NA
diffs$arrival[diffs$d2 <= 2] <- "low"
diffs$arrival[diffs$d2 >= 3] <- "high"


# 5. Dichiaro i fattori come categoriali, con ordine dei livelli


diffs$warehouse   <- factor(diffs$warehouse,   levels = c("small", "medium", "large"))
diffs$composition <- factor(diffs$composition, levels = c("small", "large"))
diffs$arrival     <- factor(diffs$arrival,     levels = c("low", "high"))

# il seed diventa un fattore categoriale: e' il "blocco".
# non mi interessa il valore del singolo seed, ma tenere conto
# del fatto che lo stesso seed compare in tutte le 12 configurazioni
diffs$seed <- factor(diffs$seed)

# controllo che la decodifica sia giusta: guardo la corrispondenza
# tra ID scenario e i tre fattori
unique(diffs[, c("Scenario", "warehouse", "composition", "arrival")])


# 6. Analisi esplorativa: vantaggio medio per scenario


# media e deviazione standard della differenza per ogni scenario
aggregate(D ~ warehouse + composition + arrival, data = diffs,
          FUN = function(x) c(media = mean(x), sd = sd(x)))


# 7. ANOVA sulle differenze (modello senza blocco)


# modello: la differenza spiegata dai tre fattori e dalle loro interazioni
model <- lm(D ~ warehouse * composition * arrival, data = diffs)

# l'intercetta dice se l'optimizer vince in media (D diverso da zero)
summary(model)

# la tabella ANOVA dice quali fattori influenzano il vantaggio
anova(model)

library(effectsize)
eta_squared(model, partial = FALSE)


# 7b. ANOVA con il seed come blocco


# stesso modello dei tre fattori, ma aggiungo il seed come effetto additivo.
# se lo stesso seed tende a produrre differenze D sistematicamente piu' alte
# o piu' basse in tutte le configurazioni, il termine seed lo assorbe.
# lo aggiungo solo come effetto principale (blocco additivo), senza
# interazioni con i tre fattori: un blocco serve a catturare uno spostamento
# medio per seed, non a modellare interazioni.
model_block <- lm(D ~ warehouse * composition * arrival + seed, data = diffs)

# guardo se il termine seed spiega varianza in modo significativo:
# se la riga "seed" nella tabella ANOVA ha p-value alto e SS piccola,
# il blocco e' trascurabile e il modello senza blocco andava gia' bene.
anova(model_block)

# effect size anche per questo modello: confronto l'eta^2 del seed
# con quello dei tre fattori. se e' minuscolo, il seed non incide.
eta_squared(model_block, partial = FALSE)

# confronto diretto dei due modelli: il test F dice se aggiungere
# il blocco seed migliora significativamente il fit.
# p-value alto => il blocco non serve, tengo il modello piu' semplice.
anova(model, model_block)

# confronto anche i coefficienti dei tre fattori tra i due modelli:
# se restano quasi identici, la presenza del blocco non cambia le conclusioni
summary(model_block)


# 8. Controllo le assunzioni (sul modello senza blocco)
# grafico dei residui per la normalita
qqnorm(residuals(model))
qqline(residuals(model), col = "red")

# grafico dei residui contro i valori predetti per la varianza costante
plot(fitted(model), residuals(model),
     xlab = "Valori predetti", ylab = "Residui")
abline(h = 0, lty = 2)


# 9. Post hoc sugli effetti significativi


# medie stimate del vantaggio per livello di arrival rate
emmeans(model, ~ arrival)

# medie stimate per warehouse e confronti a coppie
emmeans(model, ~ warehouse)
pairs(emmeans(model, ~ warehouse))