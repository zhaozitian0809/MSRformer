import torch
import torch.nn as nn
import torch.nn.functional as F
import math
import numpy as np
from torch.nn.init import _calculate_fan_in_and_fan_out
from timm.models.layers import to_2tuple, trunc_normal_
from einops import rearrange
import torch.fft as fft
from einops.layers.torch import Rearrange

class Conv2d_cd(nn.Module):
	def __init__(self, in_channels, out_channels, kernel_size=3, stride=1,
				 padding=1, dilation=1, groups=1, bias=False, theta=1.0):
		super(Conv2d_cd, self).__init__() 
		self.conv = nn.Conv2d(in_channels, out_channels, kernel_size=kernel_size, stride=stride, 
							  padding=padding, dilation=dilation, groups=groups, bias=bias)
		self.theta = theta
	
	def get_weight(self):
		conv_weight = self.conv.weight
		conv_shape = conv_weight.shape
		conv_weight = Rearrange('c_in c_out k1 k2 -> c_in c_out (k1 k2)')(conv_weight)
		conv_weight_cd = torch.cuda.FloatTensor(conv_shape[0], conv_shape[1], 3 * 3).fill_(0)
		conv_weight_cd[:, :, :] = conv_weight[:, :, :]
		conv_weight_cd[:, :, 4] = conv_weight[:, :, 4] - conv_weight[:, :, :].sum(2)
		conv_weight_cd = Rearrange('c_in c_out (k1 k2) -> c_in c_out k1 k2', k1=conv_shape[2], k2=conv_shape[3])(conv_weight_cd)
		return conv_weight_cd, self.conv.bias

class Conv2d_ad(nn.Module):
	def __init__(self, in_channels, out_channels, kernel_size=3, stride=1,
				 padding=1, dilation=1, groups=1, bias=False, theta=1.0):

		super(Conv2d_ad, self).__init__() 
		self.conv = nn.Conv2d(in_channels, out_channels, kernel_size=kernel_size, stride=stride, padding=padding, dilation=dilation, groups=groups, bias=bias)
		self.theta = theta
    
	def get_weight(self):
		conv_weight = self.conv.weight
		conv_shape = conv_weight.shape
		conv_weight = Rearrange('c_in c_out k1 k2 -> c_in c_out (k1 k2)')(conv_weight)
		conv_weight_ad = conv_weight - self.theta * conv_weight[:, :, [3, 0, 1, 6, 4, 2, 7, 8, 5]]
		conv_weight_ad = Rearrange('c_in c_out (k1 k2) -> c_in c_out k1 k2', k1=conv_shape[2], k2=conv_shape[3])(conv_weight_ad)
		return conv_weight_ad, self.conv.bias


class Conv2d_rd(nn.Module):
	def __init__(self, in_channels, out_channels, kernel_size=3, stride=1,
				 padding=2, dilation=1, groups=1, bias=False, theta=1.0):

		super(Conv2d_rd, self).__init__() 
		self.conv = nn.Conv2d(in_channels, out_channels, kernel_size=kernel_size, stride=stride, padding=padding, dilation=dilation, groups=groups, bias=bias)
		self.theta = theta

	def forward(self, x):

		if math.fabs(self.theta - 0.0) < 1e-8:
			out_normal = self.conv(x)
			return out_normal 
		else:
			conv_weight = self.conv.weight
			conv_shape = conv_weight.shape
			if conv_weight.is_cuda:
				conv_weight_rd = torch.cuda.FloatTensor(conv_shape[0], conv_shape[1], 5 * 5).fill_(0)
			else:
				conv_weight_rd = torch.zeros(conv_shape[0], conv_shape[1], 5 * 5)
			conv_weight = Rearrange('c_in c_out k1 k2 -> c_in c_out (k1 k2)')(conv_weight)
			conv_weight_rd[:, :, [0, 2, 4, 10, 14, 20, 22, 24]] = conv_weight[:, :, 1:]
			conv_weight_rd[:, :, [6, 7, 8, 11, 13, 16, 17, 18]] = -conv_weight[:, :, 1:] * self.theta
			conv_weight_rd[:, :, 12] = conv_weight[:, :, 0] * (1 - self.theta)
			conv_weight_rd = conv_weight_rd.view(conv_shape[0], conv_shape[1], 5, 5)
			out_diff = nn.functional.conv2d(input=x, weight=conv_weight_rd, bias=self.conv.bias, stride=self.conv.stride, padding=self.conv.padding, groups=self.conv.groups)

			return out_diff


class Conv2d_hd(nn.Module):
	def __init__(self, in_channels, out_channels, kernel_size=3, stride=1,
				 padding=1, dilation=1, groups=1, bias=False, theta=1.0):

		super(Conv2d_hd, self).__init__() 
		self.conv = nn.Conv1d(in_channels, out_channels, kernel_size=kernel_size, stride=stride, padding=padding, dilation=dilation, groups=groups, bias=bias)

	def get_weight(self):
		conv_weight = self.conv.weight
		conv_shape = conv_weight.shape
		conv_weight_hd = torch.cuda.FloatTensor(conv_shape[0], conv_shape[1], 3 * 3).fill_(0)
		conv_weight_hd[:, :, [0, 3, 6]] = conv_weight[:, :, :]
		conv_weight_hd[:, :, [2, 5, 8]] = -conv_weight[:, :, :]
		conv_weight_hd = Rearrange('c_in c_out (k1 k2) -> c_in c_out k1 k2', k1=conv_shape[2], k2=conv_shape[2])(conv_weight_hd)
		return conv_weight_hd, self.conv.bias


class Conv2d_vd(nn.Module):
	def __init__(self, in_channels, out_channels, kernel_size=3, stride=1,
				 padding=1, dilation=1, groups=1, bias=False):

		super(Conv2d_vd, self).__init__() 
		self.conv = nn.Conv1d(in_channels, out_channels, kernel_size=kernel_size, stride=stride, padding=padding, dilation=dilation, groups=groups, bias=bias)
    
	def get_weight(self):
		conv_weight = self.conv.weight
		conv_shape = conv_weight.shape
		conv_weight_vd = torch.cuda.FloatTensor(conv_shape[0], conv_shape[1], 3 * 3).fill_(0)
		conv_weight_vd[:, :, [0, 1, 2]] = conv_weight[:, :, :]
		conv_weight_vd[:, :, [6, 7, 8]] = -conv_weight[:, :, :]
		conv_weight_vd = Rearrange('c_in c_out (k1 k2) -> c_in c_out k1 k2', k1=conv_shape[2], k2=conv_shape[2])(conv_weight_vd)
		return conv_weight_vd, self.conv.bias


class DEConv(nn.Module):
	def __init__(self, dim):
		super(DEConv, self).__init__() 
		self.conv1_1 = Conv2d_cd(dim, dim, 3, bias=True)
		self.conv1_2 = Conv2d_hd(dim, dim, 3, bias=True)
		self.conv1_3 = Conv2d_vd(dim, dim, 3, bias=True)
		self.conv1_4 = Conv2d_ad(dim, dim, 3, bias=True)
		self.conv1_5 = nn.Conv2d(dim, dim, 3, padding=1, bias=True)

	def forward(self, x):
		w1, b1 = self.conv1_1.get_weight()
		w2, b2 = self.conv1_2.get_weight()
		w3, b3 = self.conv1_3.get_weight()
		w4, b4 = self.conv1_4.get_weight()
		w5, b5 = self.conv1_5.weight, self.conv1_5.bias

		w = w1 + w2 + w3 + w4 + w5
		b = b1 + b2 + b3 + b4 + b5
		res = nn.functional.conv2d(input=x, weight=w, bias=b, stride=1, padding=1, groups=1)

		return res

class DEBlock(nn.Module):
	def __init__(self, dim, kernel_size):
		super(DEBlock, self).__init__()
		self.conv1 = DEConv(dim)
		self.act1 = nn.ReLU(inplace=True)
		self.conv2 = nn.Conv2d(dim, dim, kernel_size, padding=(kernel_size // 2), bias=True)

	def forward(self, x):
		res = self.conv1(x)
		res = self.act1(res)
		res = res + x
		res = self.conv2(res)
		res = res + x
		return res

class RLN(nn.Module):
	r"""Revised LayerNorm"""
	def __init__(self, dim, eps=1e-5, detach_grad=False):
		super(RLN, self).__init__()
		self.eps = eps
		self.detach_grad = detach_grad

		self.weight = nn.Parameter(torch.ones((1, dim, 1, 1)))
		self.bias = nn.Parameter(torch.zeros((1, dim, 1, 1)))

		self.meta1 = nn.Conv2d(1, dim, 1)
		self.meta2 = nn.Conv2d(1, dim, 1)

		trunc_normal_(self.meta1.weight, std=.02)
		nn.init.constant_(self.meta1.bias, 1)

		trunc_normal_(self.meta2.weight, std=.02)
		nn.init.constant_(self.meta2.bias, 0)

	def forward(self, input):
		mean = torch.mean(input, dim=(1, 2, 3), keepdim=True)
		std = torch.sqrt((input - mean).pow(2).mean(dim=(1, 2, 3), keepdim=True) + self.eps)

		normalized_input = (input - mean) / std

		if self.detach_grad:
			rescale, rebias = self.meta1(std.detach()), self.meta2(mean.detach())
		else:
			rescale, rebias = self.meta1(std), self.meta2(mean)

		out = normalized_input * self.weight + self.bias
		return out, rescale, rebias


class DFFN(nn.Module):
	def __init__(self, network_depth, in_features, hidden_features=None, out_features=None):
		super(DFFN, self).__init__()
		out_features = out_features or in_features
		hidden_features = hidden_features or in_features

		self.network_depth = network_depth

		self.patch_size = 8
		self.project_in = nn.Conv2d(in_features, hidden_features * 2, kernel_size=1, bias=False)
		self.dwconv = nn.Conv2d(hidden_features * 2, hidden_features * 2, kernel_size=3, stride=1, padding=1,
								groups=hidden_features * 2, bias=False)
		self.fft = nn.Parameter(torch.ones((hidden_features * 2, 1, 1, self.patch_size, self.patch_size // 2 + 1)))
		self.project_out = nn.Conv2d(hidden_features, out_features, kernel_size=1, bias=False)


		self.apply(self._init_weights)

	def _init_weights(self, m):
		if isinstance(m, nn.Conv2d):
			gain = (8 * self.network_depth) ** (-1/4)
			fan_in, fan_out = _calculate_fan_in_and_fan_out(m.weight)
			std = gain * math.sqrt(2.0 / float(fan_in + fan_out))
			trunc_normal_(m.weight, std=std)
			if m.bias is not None:
				nn.init.constant_(m.bias, 0)

	def forward(self, x):
		x = self.project_in(x)
		x_patch = rearrange(x, 'b c (h patch1) (w patch2) -> b c h w patch1 patch2', patch1=self.patch_size,
							patch2=self.patch_size)
		x_patch_fft = torch.fft.rfft2(x_patch.float())
		x_patch_fft = x_patch_fft * self.fft
		x_patch = torch.fft.irfft2(x_patch_fft, s=(self.patch_size, self.patch_size))
		x = rearrange(x_patch, 'b c h w patch1 patch2 -> b c (h patch1) (w patch2)', patch1=self.patch_size,
					  patch2=self.patch_size)
		x1, x2 = self.dwconv(x).chunk(2, dim=1)

		x = F.gelu(x1) * x2
		x = self.project_out(x)
		return x


def window_partition(x, window_size):
	B, H, W, C = x.shape
	x = x.view(B, H // window_size, window_size, W // window_size, window_size, C)
	windows = x.permute(0, 1, 3, 2, 4, 5).contiguous().view(-1, window_size**2, C)  
	return windows  # (B*H*W/window_size**2, window_size**2, C)


def window_reverse(windows, window_size, H, W):
	B = int(windows.shape[0] / (H * W / window_size / window_size))
	x = windows.view(B, H // window_size, W // window_size, window_size, window_size, -1)
	x = x.permute(0, 1, 3, 2, 4, 5).contiguous().view(B, H, W, -1)
	return x  # (B, H, W, C)


def get_relative_positions(window_size):
	coords_h = torch.arange(window_size)
	coords_w = torch.arange(window_size)

	coords = torch.stack(torch.meshgrid([coords_h, coords_w]))  # 2, Wh, Ww
	coords_flatten = torch.flatten(coords, 1)  # 2, Wh*Ww
	relative_positions = coords_flatten[:, :, None] - coords_flatten[:, None, :]  # 2, Wh*Ww, Wh*Ww

	relative_positions = relative_positions.permute(1, 2, 0).contiguous()  # Wh*Ww, Wh*Ww, 2
	relative_positions_log  = torch.sign(relative_positions) * torch.log(1. + relative_positions.abs())

	return relative_positions_log


class WindowAttention(nn.Module):
	def __init__(self, dim, window_size, num_heads):

		super().__init__()
		self.dim = dim
		self.window_size = window_size  # Wh, Ww
		self.num_heads = num_heads
		head_dim = dim // num_heads
		self.scale = head_dim ** -0.5

		relative_positions = get_relative_positions(self.window_size)
		self.register_buffer("relative_positions", relative_positions)
		self.meta = nn.Sequential(
			nn.Linear(2, 256, bias=True),
			nn.ReLU(True),
			nn.Linear(256, num_heads, bias=True)
		)

		self.softmax = nn.Softmax(dim=-1)
		self.patch_size = 8


	def forward(self, qkv):
		B_, N, _ = qkv.shape

		qkv = qkv.reshape(B_, N, 3, self.num_heads, self.dim // self.num_heads).permute(2, 0, 3, 1, 4)

		q, k, v = qkv[0], qkv[1], qkv[2]  # make torchscript happy (cannot use tensor as tuple)
		q = q * self.scale
		
		q_patch = rearrange(q, 'a b (c patch1 patch2) d -> a b c d patch1 patch2', patch1=self.patch_size,
							patch2=self.patch_size)
		k_patch = rearrange(k, 'a b (c patch1 patch2) d -> a b c d patch1 patch2', patch1=self.patch_size,
							patch2=self.patch_size)
		q_fft = torch.fft.rfft2(q_patch.float())
		k_fft = torch.fft.rfft2(k_patch.float())
		out = q_fft * k_fft
		out = torch.fft.irfft2(out, s=(self.patch_size, self.patch_size))
		out = rearrange(out, 'a b c d patch1 patch2 -> a b (c patch1 patch2) d' , patch1=self.patch_size,
							patch2=self.patch_size)
		
		
		relative_position_bias = self.meta(self.relative_positions)
		relative_position_bias = relative_position_bias.permute(2, 0, 1).contiguous()  # nH, Wh*Ww, Wh*Ww
		attn = (out @ v.transpose(-2, -1))
		attn = attn + relative_position_bias.unsqueeze(0)

		attn = self.softmax(attn)

		x = (attn @ v).transpose(1, 2).reshape(B_, N, self.dim)
		return x


class Attention(nn.Module):
	def __init__(self, network_depth, dim, num_heads, window_size, shift_size, use_attn=False, conv_type=None):
		super().__init__()
		self.dim = dim
		self.head_dim = int(dim // num_heads)
		self.num_heads = num_heads

		self.window_size = window_size
		self.shift_size = shift_size

		self.network_depth = network_depth
		self.use_attn = use_attn
		self.conv_type = conv_type
		self.deblock = DEBlock(dim , 3)

		if self.conv_type == 'Conv':
			self.conv = nn.Sequential(
				nn.Conv2d(dim, dim, kernel_size=3, padding=1, padding_mode='reflect'),
				nn.ReLU(True),
				nn.Conv2d(dim, dim, kernel_size=3, padding=1, padding_mode='reflect')
			)

		if self.conv_type == 'DWConv':
			self.conv = nn.Conv2d(dim, dim, kernel_size=5, padding=2, groups=dim, padding_mode='reflect')

		if self.conv_type == 'DWConv' or self.use_attn:
			self.V = nn.Conv2d(dim, dim, 1)
			self.proj = nn.Conv2d(dim, dim, 1)
			self.proj2 = nn.Conv2d(dim, dim, 1)
			self.proj3 = nn.Conv2d(dim, dim, kernel_size=3, stride=1, padding=1)

		if self.use_attn:
			self.QK = nn.Conv2d(dim, dim * 2, 1)
			self.attn = WindowAttention(dim, window_size, num_heads)

		self.apply(self._init_weights)

	def _init_weights(self, m):
		if isinstance(m, nn.Conv2d):
			w_shape = m.weight.shape
			
			if w_shape[0] == self.dim * 2:	# QK
				fan_in, fan_out = _calculate_fan_in_and_fan_out(m.weight)
				std = math.sqrt(2.0 / float(fan_in + fan_out))
				trunc_normal_(m.weight, std=std)		
			else:
				gain = (8 * self.network_depth) ** (-1/4)
				fan_in, fan_out = _calculate_fan_in_and_fan_out(m.weight)
				std = gain * math.sqrt(2.0 / float(fan_in + fan_out))
				trunc_normal_(m.weight, std=std)

			if m.bias is not None:
				nn.init.constant_(m.bias, 0)

	def check_size(self, x, shift=False):
		_, _, h, w = x.size()
		mod_pad_h = (self.window_size - h % self.window_size) % self.window_size
		mod_pad_w = (self.window_size - w % self.window_size) % self.window_size

		if shift:
			x = F.pad(x, (self.shift_size, (self.window_size-self.shift_size+mod_pad_w) % self.window_size,
						  self.shift_size, (self.window_size-self.shift_size+mod_pad_h) % self.window_size), mode='reflect')
		else:
			x = F.pad(x, (0, mod_pad_w, 0, mod_pad_h), 'reflect')
		return x

	def forward(self, X):
		B, C, H, W = X.shape

		if self.conv_type == 'DWConv' or self.use_attn:
			V = self.V(X)

		if self.use_attn:
			QK = self.QK(X)
			QKV = torch.cat([QK, V], dim=1)

			# shift
			shifted_QKV = self.check_size(QKV, self.shift_size > 0)
			Ht, Wt = shifted_QKV.shape[2:]

			# partition windows
			shifted_QKV = shifted_QKV.permute(0, 2, 3, 1)
			qkv = window_partition(shifted_QKV, self.window_size)  # nW*B, window_size**2, C

			attn_windows = self.attn(qkv)

			# merge windows
			shifted_out = window_reverse(attn_windows, self.window_size, Ht, Wt)  # B H' W' C

			# reverse cyclic shift
			out = shifted_out[:, self.shift_size:(self.shift_size+H), self.shift_size:(self.shift_size+W), :]
			attn_out = out.permute(0, 3, 1, 2)

			if self.conv_type in ['Conv', 'DWConv']:
				conv_out = self.conv(V)
				out = self.proj(conv_out + attn_out)
			# DEB
				deb_out = self.proj3(out)
				deb_out = self.deblock(deb_out)
				out = self.proj2(out + deb_out)

				
				
			else:
				out = self.proj(attn_out)

		else:
			if self.conv_type == 'Conv':
				out = self.conv(X)				# no attention and use conv, no projection
			elif self.conv_type == 'DWConv':
				out = self.proj(self.conv(V))

		return out


class TransformerBlock(nn.Module):
	def __init__(self, network_depth, dim, num_heads, mlp_ratio=2.66,
				 norm_layer=nn.LayerNorm, mlp_norm=False,
				 window_size=8, shift_size=0, use_attn=True, conv_type=None):
		super().__init__()
		self.use_attn = use_attn
		self.mlp_norm = mlp_norm

		self.norm1 = norm_layer(dim) if use_attn else nn.Identity()
		self.attn = Attention(network_depth, dim, num_heads=num_heads, window_size=window_size,
							  shift_size=shift_size, use_attn=use_attn, conv_type=conv_type)

		self.norm2 = norm_layer(dim) if use_attn and mlp_norm else nn.Identity()
		self.ffn = DFFN(network_depth, dim, hidden_features=int(dim * mlp_ratio))

	def forward(self, x):
		identity = x
		if self.use_attn: x, rescale, rebias = self.norm1(x)
		x = self.attn(x)
		if self.use_attn: x = x * rescale + rebias
		x = identity + x

		identity = x
		if self.use_attn and self.mlp_norm: x, rescale, rebias = self.norm2(x)
		x = self.ffn(x)
		if self.use_attn and self.mlp_norm: x = x * rescale + rebias
		x = identity + x
		return x


class BasicLayer(nn.Module):
	def __init__(self, network_depth, dim, depth, num_heads, mlp_ratio=2.66,
				 norm_layer=nn.LayerNorm, window_size=8,
				 attn_ratio=0., attn_loc='last', conv_type=None):

		super().__init__()
		self.dim = dim
		self.depth = depth

		attn_depth = attn_ratio * depth

		if attn_loc == 'last':
			use_attns = [i >= depth-attn_depth for i in range(depth)]
		elif attn_loc == 'first':
			use_attns = [i < attn_depth for i in range(depth)]
		elif attn_loc == 'middle':
			use_attns = [i >= (depth-attn_depth)//2 and i < (depth+attn_depth)//2 for i in range(depth)]

		# build blocks
		self.blocks = nn.ModuleList([
			TransformerBlock(network_depth=network_depth,
							 dim=dim, 
							 num_heads=num_heads,
							 mlp_ratio=mlp_ratio,
							 norm_layer=norm_layer,
							 window_size=window_size,
							 shift_size=0 if (i % 2 == 0) else window_size // 2,
							 use_attn=use_attns[i], conv_type=conv_type)
			for i in range(depth)])

	def forward(self, x):
		for blk in self.blocks:
			x = blk(x)
		return x


class PatchEmbed(nn.Module):
	def __init__(self, patch_size=4, in_chans=3, embed_dim=96, kernel_size=None):
		super().__init__()
		self.in_chans = in_chans
		self.embed_dim = embed_dim

		if kernel_size is None:
			kernel_size = patch_size

		self.proj = nn.Conv2d(in_chans, embed_dim, kernel_size=kernel_size, stride=patch_size,
							  padding=(kernel_size-patch_size+1)//2, padding_mode='reflect')

	def forward(self, x):
		x = self.proj(x)
		return x


class PatchUnEmbed(nn.Module):
	def __init__(self, patch_size=4, out_chans=3, embed_dim=96, kernel_size=None):
		super().__init__()
		self.out_chans = out_chans
		self.embed_dim = embed_dim

		if kernel_size is None:
			kernel_size = 1

		self.proj = nn.Sequential(
			nn.Conv2d(embed_dim, out_chans*patch_size**2, kernel_size=kernel_size,
					  padding=kernel_size//2, padding_mode='reflect'),
			nn.PixelShuffle(patch_size)
		)

	def forward(self, x):
		x = self.proj(x)
		return x


class SpatialAttention(nn.Module):
	def __init__(self):
		super(SpatialAttention, self).__init__()
		self.sa = nn.Conv2d(2, 1, 7, padding=3, padding_mode='reflect' ,bias=True)

	def forward(self, x):
		x_avg = torch.mean(x, dim=1, keepdim=True)
		x_max, _ = torch.max(x, dim=1, keepdim=True)
		x2 = torch.concat([x_avg, x_max], dim=1)
		sattn = self.sa(x2)
		return sattn


class ChannelAttention(nn.Module):
	def __init__(self, dim, reduction = 8):
		super(ChannelAttention, self).__init__()
		self.gap = nn.AdaptiveAvgPool2d(1)
		self.ca = nn.Sequential(
			nn.Conv2d(dim, dim // reduction, 1, padding=0, bias=True),
			nn.ReLU(inplace=True),
			nn.Conv2d(dim // reduction, dim, 1, padding=0, bias=True),
		)

	def forward(self, x):
		x_gap = self.gap(x)
		cattn = self.ca(x_gap)
		return cattn

    
class PixelAttention(nn.Module):
	def __init__(self, dim):
		super(PixelAttention, self).__init__()
		self.pa2 = nn.Conv2d(2 * dim, dim, 7, padding=3, padding_mode='reflect' ,groups=dim, bias=True)
		self.sigmoid = nn.Sigmoid()

	def forward(self, x, pattn1):
		B, C, H, W = x.shape
		x = x.unsqueeze(dim=2) # B, C, 1, H, W
		pattn1 = pattn1.unsqueeze(dim=2) # B, C, 1, H, W
		x2 = torch.cat([x, pattn1], dim=2) # B, C, 2, H, W
		x2 = Rearrange('b c t h w -> b (c t) h w')(x2)
		pattn2 = self.pa2(x2)
		pattn2 = self.sigmoid(pattn2)
		return pattn2


class CGAFusion(nn.Module):
	def __init__(self, dim, reduction=8):
		super(CGAFusion, self).__init__()
		
		self.sa = SpatialAttention()
		self.ca = ChannelAttention(dim, reduction)
		self.pa = PixelAttention(dim)
		self.conv = nn.Conv2d(dim, dim, 1, bias=True)
		self.sigmoid = nn.Sigmoid()

	def forward(self, x, y):
		initial = x + y
		cattn = self.ca(initial)
		sattn = self.sa(initial)
		pattn1 = sattn + cattn
		pattn2 = self.sigmoid(self.pa(initial, pattn1))
		result = initial + pattn2 * x + (1 - pattn2) * y
		result = self.conv(result)
		return result      


class MSRFormer(nn.Module):
	def __init__(self, in_chans=3, out_chans=4, window_size=8,
				 embed_dims=[24, 48, 96, 48, 24],
				 mlp_ratios=[2.66, 3, 3, 3, 2.66],
				 depths=[16, 16, 16, 8, 8],
				 num_heads=[2, 4, 6, 1, 1],
				 attn_ratio=[1/4, 1/2, 3/4, 0, 0],
				 conv_type=['DWConv', 'DWConv', 'DWConv', 'DWConv', 'DWConv'],
				 norm_layer=[RLN, RLN, RLN, RLN, RLN]):
		super(MSRFormer, self).__init__()

		# setting
		self.patch_size = 4
		self.window_size = window_size
		self.mlp_ratios = mlp_ratios

		# split image into non-overlapping patches
		self.patch_embed = PatchEmbed(
			patch_size=1, in_chans=in_chans, embed_dim=embed_dims[0], kernel_size=3)

		# backbone
		self.layer1 = BasicLayer(network_depth=sum(depths), dim=embed_dims[0], depth=depths[0],
					   			 num_heads=num_heads[0], mlp_ratio=mlp_ratios[0],
					   			 norm_layer=norm_layer[0], window_size=window_size,
					   			 attn_ratio=attn_ratio[0], attn_loc='last', conv_type=conv_type[0])

		self.patch_merge1 = PatchEmbed(
			patch_size=2, in_chans=embed_dims[0], embed_dim=embed_dims[1])

		self.skip1 = nn.Conv2d(embed_dims[0], embed_dims[0], 1)

		self.layer2 = BasicLayer(network_depth=sum(depths), dim=embed_dims[1], depth=depths[1],
								 num_heads=num_heads[1], mlp_ratio=mlp_ratios[1],
								 norm_layer=norm_layer[1], window_size=window_size,
								 attn_ratio=attn_ratio[1], attn_loc='last', conv_type=conv_type[1])

		self.patch_merge2 = PatchEmbed(
			patch_size=2, in_chans=embed_dims[1], embed_dim=embed_dims[2])

		self.skip2 = nn.Conv2d(embed_dims[1], embed_dims[1], 1)

		self.layer3 = BasicLayer(network_depth=sum(depths), dim=embed_dims[2], depth=depths[2],
								 num_heads=num_heads[2], mlp_ratio=mlp_ratios[2],
								 norm_layer=norm_layer[2], window_size=window_size,
								 attn_ratio=attn_ratio[2], attn_loc='last', conv_type=conv_type[2])

		self.patch_split1 = PatchUnEmbed(
			patch_size=2, out_chans=embed_dims[3], embed_dim=embed_dims[2])

		assert embed_dims[1] == embed_dims[3]
		self.fusion1 = CGAFusion(embed_dims[3])

		self.layer4 = BasicLayer(network_depth=sum(depths), dim=embed_dims[3], depth=depths[3],
								 num_heads=num_heads[3], mlp_ratio=mlp_ratios[3],
								 norm_layer=norm_layer[3], window_size=window_size,
								 attn_ratio=attn_ratio[3], attn_loc='last', conv_type=conv_type[3])

		self.patch_split2 = PatchUnEmbed(
			patch_size=2, out_chans=embed_dims[4], embed_dim=embed_dims[3])

		assert embed_dims[0] == embed_dims[4]
		self.fusion2 = CGAFusion(embed_dims[4])			

		self.layer5 = BasicLayer(network_depth=sum(depths), dim=embed_dims[4], depth=depths[4],
					   			 num_heads=num_heads[4], mlp_ratio=mlp_ratios[4],
					   			 norm_layer=norm_layer[4], window_size=window_size,
					   			 attn_ratio=attn_ratio[4], attn_loc='last', conv_type=conv_type[4])

		# merge non-overlapping patches into image
		self.patch_unembed = PatchUnEmbed(
			patch_size=1, out_chans=out_chans, embed_dim=embed_dims[4], kernel_size=3)


	def check_image_size(self, x):
		# NOTE: for I2I test
		_, _, h, w = x.size()
		mod_pad_h = (self.patch_size - h % self.patch_size) % self.patch_size
		mod_pad_w = (self.patch_size - w % self.patch_size) % self.patch_size
		x = F.pad(x, (0, mod_pad_w, 0, mod_pad_h), 'reflect')
		return x

	def forward_features(self, x):
		x = self.patch_embed(x)
		x = self.layer1(x)
		skip1 = x

		x = self.patch_merge1(x)
		x = self.layer2(x)
		skip2 = x

		x = self.patch_merge2(x)
		x = self.layer3(x)
		x = self.patch_split1(x)

		x = self.fusion1(x, self.skip2(skip2)) + x
		x = self.layer4(x)
		x = self.patch_split2(x)

		x = self.fusion2(x, self.skip1(skip1)) + x
		x = self.layer5(x)
		x = self.patch_unembed(x)
		return x

	def forward(self, x):
		H, W = x.shape[2:]
		x = self.check_image_size(x)

		feat = self.forward_features(x)
		K, B = torch.split(feat, (1, 3), dim=1)

		x = K * x - B + x
		x = x[:, :, :H, :W]
		return x

def MSRFormer_s():
    return MSRFormer(
		embed_dims=[24, 48, 96, 48, 24],
		mlp_ratios=[2.66, 3, 3, 3, 2.66],
		depths=[8, 8, 8, 4, 4],
		num_heads=[2, 4, 6, 1, 1],
		attn_ratio=[1/4, 1/2, 3/4, 0, 0],
		conv_type=['DWConv', 'DWConv', 'DWConv', 'DWConv', 'DWConv'])


def MSRFormer_l():
    return MSRFormer(
		embed_dims=[48, 96, 192, 96, 48],
		mlp_ratios=[2.66, 3, 3, 3, 2.66],
		depths=[16, 16, 16, 12, 12],
		num_heads=[2, 4, 6, 1, 1],
		attn_ratio=[1/4, 1/2, 3/4, 0, 0],
		conv_type=['Conv', 'Conv', 'Conv', 'Conv', 'Conv'])