import torch
import numpy as np
from src.network import NetworkCNN
import matplotlib.pyplot as plt



class DPG(object):
	"""
	Deterministic Policy Gradient
	"""

	def __init__(self, config, dataset) -> None:
		self.config = config # yaml parser (can be accessed as dictionary). See `config/ ... .yml` file
		self.feature_num = config["inputs"]["feature_number"]
		# self.coin_num = config["input"]["coin_num"]
		self.coin_num = len(config["dataset"]["currencies"])
		self.window_size = config["inputs"]["window_size"] # nb = 50, window size (size of X).

		self.price_data, self.Y = dataset.dataset # Dataset source is defined in `run.py`. Example = marketData_CSV()
		self.total_timeStep = self.price_data.shape[1] # Total time step inside dataset

		self.pvm = PVM(self.total_timeStep, self.coin_num) # Replay buffer
		self.NNmodel = NetworkCNN(feature_number=self.feature_num, num_currencies=self.coin_num, window_size=self.window_size )
		# self.NNmodel = self.NNmodel.to(torch.double) 
		self.optimizer = torch.optim.Adam(self.NNmodel.parameters())

		self.beta = config["hyperparams"]["beta"] # = probability-decaying rate determining the shape of the probability distribution for sampling tb for training NN
		self.Nb = config["hyperparams"]["mini_batch"] # = 50, mini batch size
		self.mu_t = config["hyperparams"]["comission_rate"] # 0.0025 commision rate (constant, cp=cs)
		self.lr = config["hyperparams"]["learning_rate"]

		self.p_0 = config["inputs"]["init_value"]
		# self.portValues = []
		self.portValues = None

		
	def train(self):
		"""
		Run training process
		"""
		t = 0
		while True:
			t += 1

			# Because X size is window_size --> 50
			if t >= self.window_size:
				# Get a batch price data at time step t, take portfolio vector from replay buffer, and do forward pass
				X = self.get_X(t)
				w = self.pvm.get_previous_w(t)
				
				# w_out = self.take_action(X, w) # forward pass of neural network
				print("w: ", w)
				print("w.shape: ", w.shape)
				print(w[:,1:,:].shape)
				print(w[:,1:,:])


				# w = w.to(torch.float64)
				# X = X.to(torch.float64)
				w_out = self.take_action(X, w[:, 1:, :]) # w.shape: (1, currency, 1). Excluding cash currency




				print(w_out)
				# PAY ATTENTION to whether cash coin included in the tensor or not!
				# Store sample path into replay buffer
				# self.pvm.store_portfolio_vector(w_out.detach().numpy()[0,1:,0], t)
				self.pvm.store_portfolio_vector(w_out.detach().numpy()[0,:,0], t)

				# Store cumulative portfolio value
				self.store_cumPortVal(t)

			# Start training after ... time steps (after portvolio vector memory filled), and update neural network every ... time step freq
			# if t >= self.config["hyperparams"]["train_start"] and t % self.config["hyperparams"]["train_freq"] == 0 :
			# # Learning one step using batch of data from replay buffer.
			#     train_batch = self.get_sample_batch(t)
			#     self.update_step(train_batch)

			# Finish training at these conditions
			if t >= self.total_timeStep-1:
				break

		self.plot_output()
	
	def get_X(self, t):
		"""
		get X input at time step t.
		self.price_data.shape : (feature, total_time_step, currencies_(excluding cash!))
		X.shape : torch.Size([1, feature, currencies, window_size])
		'allprices in the input tensor will be normalization by the latest closing prices'
		"""
		# X = self.price_data[:, t-self.nb:t, :] / self.price_data[:, t-1, :]

		# Cash currency is NOT INCLUDED
		X = self.price_data[:, t-self.window_size:t, 1:] / self.price_data[0, t-1, 1:] # Need to double check
		X = X.transpose(0, 2, 1)
		X = np.expand_dims(X, axis=0).astype(np.float64)
		# X = torch.from_numpy(X)
		X = torch.tensor(X)
		return X

	def calc_portValue(self, t):
		return np.sum(self.mu_t * self.Y[t] * self.pvm.get_previous_w(t).detach().numpy())
	
	def store_cumPortVal(self, t):
		"""
		Calculate portfolio value at given step: sum of ( price of each asset times weight of each asset)
		"""
		# if len(self.portValues) == 0:
			# self.portValues.append(self.p_0)

		if self.portValues is None:
			self.portValues = np.insert(np.zeros(self.coin_num), 0, self.p_0)
			self.portValues = np.expand_dims(self.portValues, axis=0)

		# Equation (11) in paper
		cum_portVal = self.portValues[-1].sum() * self.calc_portValue(t)
		# self.portValues.append(cum_portVal)
		self.portValues = np.vstack((self.portValues, cum_portVal))
		# import pdb; pdb.set_trace()

	def take_action(self, X, w):
		"""
		Get action (portfolio weight vector) by doing inference on neural network
		"""
		return self.NNmodel(X, w) # NN model take price data input and previous portfolio weight

	def update_step(self, train_batch):
		"""
		One neural network training update step.
		Use sample batch.
		"""
		self.optimizer.zero_grad()
		loss = self.calc_loss(train_batch) * -1
		loss.backward()
		self.optimizer.step()

	def calc_loss(self, train_batch):
		"""
		Calculate loss function. 
		Use batch (take from self.get_batch())
		"""
		X, prev_w, tb = train_batch
		w_out = self.take_action(X, prev_w)

		tb = tb + 1


		# Calculate the loss

		pass

	def tb_sampling(self, t):
		def geometricDist(tb, beta):
			"""Probability mass function of geometric distribution"""
			return beta * (1 - beta) ** (tb)
		
		# PMF of geometric distribution, reversed
		distribution = geometricDist(np.arange(t-self.window_size), self.beta)[::-1]
		# import pdb; pdb.set_trace()

		return np.random.choice(t-self.window_size, self.Nb, p=distribution, replace=False)


	def get_sample_batch(self, t):
		"""
		Get a batch of path sample randomly from price matrix and self.pvm (PVM() class)
		---
		X_samples: torch.Tensor
		w_samples: torch.Tensor
		tb_samples: numpy.Array
		"""
		tb_samples = self.tb_sampling(t)
		X_samples = None
		w_samples = None
		for tb in tb_samples:
			if X_samples == None:
				X_samples = self.get_X(tb)
				w_samples = self.pvm.get_previous_w(tb)
			else:
				X_samples = torch.cat([X_samples, self.get_X(tb)], dim=0)
				w_samples = torch.cat([w_samples, self.pvm.get_previous_w(tb)], dim=0)

		return X_samples, w_samples, tb_samples

	def save_model(self):
		"""
		Save neural network parameter weights as `model.pth` and output rewards as Numpy .npy file.
		"""
		pass

	def plot_output(self):
		"""
		Create output plot.
		"""
		plt.plot(self.portValues.sum(axis=1))
		plt.grid(axis='x', color='0.95')
		plt.xlabel('t')
		plt.ylabel('portfolio value')
		plt.savefig('port-value.png')

	def run_training(self):
		# print("Shape of dataset.dataset: ", self.price_data.shape)
		# print("Shape of self.get_X(): ", self.get_X(100).shape)
		# print("Sampling t from geometry distribution will look like this", self.tb_sampling(1000))
		# print("\nSee `run_training()` method and uncomment `self.train()`")
		# import pdb; pdb.set_trace()
		self.train() # Run training process. Arguments for self.train() will be defined here.


class PVM():
	"""Portfolio Vector Memory; a stack of portfolio vectors in chronological order"""

	def __init__(self, total_timeStep, coin_num):
		# On initialization, add portfolio vector [1, 0, ..., 0] (1 for 'cash' currency)
		self.total_timeStep = total_timeStep
		self.coin_num = coin_num
		self.memory = np.zeros((self.total_timeStep, self.coin_num)) #, dtype=np.float32)
		cash = np.ones((self.total_timeStep, 1))
		self.memory = np.concatenate((cash, self.memory), axis=1)
		# self.next_idx = 0

	def store_portfolio_vector(self, w, t):
		"""
		Store portfolio vector.
		Note: 
		"""
		# self.memory[self.next_idx] = w
		self.memory[t] = w
		# self.next_idx += 1

	def get_previous_w(self, t):
		"""
		Take previous portfolio vector at time step t
		"""
		w = self.memory[t-1]
		w = np.expand_dims(w, axis=0)
		w = np.expand_dims(w, axis=-1)
		# w = torch.from_numpy(w).to(torch.double)
		w = torch.from_numpy(w)
		# import pdb; pdb.set_trace()
		return w

	
