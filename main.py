from config import config, log_config
from utils import *
from model import *

import tensorflow as tf
import tensorlayer as tl
import numpy as np
from random import shuffle
import matplotlib
import datetime
import time
import shutil
from flip_gradient import flip_gradient            

batch_size = config.TRAIN.batch_size
batch_size_init = config.TRAIN.batch_size_init
lr_init = config.TRAIN.lr_init
beta1 = config.TRAIN.beta1

n_epoch = config.TRAIN.n_epoch
n_epoch_init = config.TRAIN.n_epoch_init
lr_decay = config.TRAIN.lr_decay
decay_every = config.TRAIN.decay_every

lambda_tv = config.TRAIN.lambda_tv

h = config.TRAIN.height
w = config.TRAIN.width

ni = int(np.ceil(np.sqrt(batch_size)))

def read_all_imgs(img_list, path = '', n_threads = 32, mode = 'RGB'):
    for idx in range(0, len(img_list), n_threads):
        if idx + n_threads > len(img_list):
            break;
            
        b_imgs_list = img_list[idx : idx + n_threads]
        if mode is 'RGB':
            if idx == 0:
                b_imgs = tl.prepro.threading_data(b_imgs_list, fn = get_imgs_RGB_fn, path = path)
            else:
                imgs = tl.prepro.threading_data(b_imgs_list, fn = get_imgs_RGB_fn, path = path)
                b_imgs = np.concatenate((b_imgs, imgs), axis = 0)
                
        elif mode is 'GRAY':
            if idx == 0:
                b_imgs = tl.prepro.threading_data(b_imgs_list, fn = get_imgs_GRAY_fn, path = path)
            else:
                imgs = tl.prepro.threading_data(b_imgs_list, fn = get_imgs_GRAY_fn, path = path)
                b_imgs = np.concatenate((b_imgs, imgs), axis = 0)
        
    return b_imgs
   
def train():
    ## CREATE DIRECTORIES
    mode_dir = config.TRAIN.root_dir + '{}'.format(tl.global_flag['mode'])

    ckpt_dir = mode_dir + '/checkpoint'
    init_dir = mode_dir + '/init'
    log_dir = mode_dir + '/log'
    sample_dir = mode_dir + '/samples/0_train'
    config_dir = mode_dir + '/config'

    if tl.global_flag['delete_log']:
        shutil.rmtree(ckpt_dir, ignore_errors = True)
        shutil.rmtree(log_dir, ignore_errors = True)
        shutil.rmtree(sample_dir, ignore_errors = True)
        shutil.rmtree(config_dir, ignore_errors = True)

    tl.files.exists_or_mkdir(ckpt_dir)
    tl.files.exists_or_mkdir(init_dir)
    tl.files.exists_or_mkdir(log_dir)
    tl.files.exists_or_mkdir(sample_dir)
    tl.files.exists_or_mkdir(config_dir)
    log_config(config_dir, config)

    ## DEFINE SESSION
    sess = tf.Session(config = tf.ConfigProto(allow_soft_placement = True, log_device_placement = False))
    
    ## READ DATASET LIST
    train_synthetic_img_list = np.array(sorted(tl.files.load_file_list(path = config.TRAIN.synthetic_img_path, regx = '.*', printable = False)))
    train_defocus_map_list = np.array(sorted(tl.files.load_file_list(path = config.TRAIN.defocus_map_path, regx = '.*', printable = False)))
    train_synthetic_binary_map_list = np.array(sorted(tl.files.load_file_list(path = config.TRAIN.synthetic_binary_map_path, regx = '.*', printable = False)))
    
    train_real_img_list = np.array(sorted(tl.files.load_file_list(path = config.TRAIN.real_img_path, regx = '.*', printable = False)))
    train_real_binary_map_list = np.array(sorted(tl.files.load_file_list(path = config.TRAIN.real_binary_map_path, regx = '.*', printable = False)))

    ## DEFINE MODEL
    # input
    with tf.variable_scope('input'):
        patches_synthetic = tf.placeholder('float32', [None, h, w, 3], name = 'input_synthetic')
        labels_synthetic_defocus = tf.placeholder('float32', [None, h, w, 1], name = 'labels_synthetic')
        labels_synthetic_binary = tf.placeholder('float32', [None, h, w, 1], name = 'labels_synthetic')

        patches_real = tf.placeholder('float32', [None, h, w, 3], name = 'input_real')
        labels_real_binary = tf.placeholder('float32', [None, h, w, 1], name = 'labels_real_binary')

    # model
    with tf.variable_scope('defocus_net') as scope:
        with tf.variable_scope('unet') as scope:
            with tf.variable_scope('unet_down') as scope:
                f0_synthetic, f1_2_synthetic, f2_3_synthetic, f3_4_synthetic, final_feature_synthetic = UNet_down(patches_synthetic, is_train = True, reuse = False, scope = scope)
                f0_real, f1_2_real, f2_3_real, f3_4_real, final_feature_real = UNet_down(patches_real, is_train = True, reuse = True, scope = scope)

        with tf.variable_scope('domain_lambda_predictor') as scope:
            domain_lambda_synthetic = domain_lambda_predictor(final_feature_synthetic, reuse = False, scope = scope)
            domain_lambda_real = domain_lambda_predictor(final_feature_real, reuse = True, scope = scope)

            f_f0_synthetic = flip_gradient(f0_synthetic, domain_lambda_synthetic)
            f_f1_2_synthetic = flip_gradient(f1_2_synthetic, domain_lambda_synthetic)
            f_f2_3_synthetic = flip_gradient(f2_3_synthetic, domain_lambda_synthetic)
            f_f3_4_synthetic = flip_gradient(f3_4_synthetic, domain_lambda_synthetic)
            f_final_feature_synthetic = flip_gradient(final_feature_synthetic, domain_lambda_synthetic)
            
            f_f0_real = flip_gradient(f0_real, domain_lambda_real)
            f_f1_2_real = flip_gradient(f1_2_real, domain_lambda_real)
            f_f2_3_real = flip_gradient(f2_3_real, domain_lambda_real)
            f_f3_4_real = flip_gradient(f3_4_real, domain_lambda_real)
            f_final_feature_real = flip_gradient(final_feature_real, domain_lambda_real)
                    
        with tf.variable_scope('discriminator') as scope:
            d_logits_synthetic = SRGAN_d(f_f0_synthetic, f_f1_2_synthetic, f_f2_3_synthetic, f_f3_4_synthetic, f_final_feature_synthetic, is_train = True, reuse = False, scope = scope)
            d_logits_real = SRGAN_d(f_f0_real, f_f1_2_real, f_f2_3_real, f_f3_4_real, f_final_feature_real, is_train = True, reuse = True, scope = scope)

        with tf.variable_scope('unet') as scope:
            with tf.variable_scope('binary_net') as scope:
                with tf.variable_scope('unet_up_defocus_map') as scope:
                    output_synthetic_defocus_logits, output_synthetic_defocus = UNet_up(f0_synthetic, f1_2_synthetic, f2_3_synthetic, f3_4_synthetic, final_feature_synthetic, h, w, is_train = True, reuse = False, scope = scope)
                    output_real_defocus_logits, output_real_defocus = UNet_up(f0_real, f1_2_real, f2_3_real, f3_4_real, final_feature_real, h, w, is_train = True, reuse = True, scope = scope)

                output_synthetic_binary_logits, output_synthetic_binary = Binary_Net(output_synthetic_defocus, is_train = True, reuse = False, scope = scope)
                output_real_binary_logits, output_real_binary = Binary_Net(output_real_defocus, is_train = True, reuse = True, scope = scope)
    
    ## DEFINE LOSS
    with tf.variable_scope('loss'):
        with tf.variable_scope('domain'):
            loss_synthetic_domain = tl.cost.sigmoid_cross_entropy(d_logits_synthetic, tf.zeros_like(d_logits_synthetic), name = 'synthetic')
            loss_real_domain = tl.cost.sigmoid_cross_entropy(d_logits_real, tf.ones_like(d_logits_real), name = 'real')
            loss_domain = tf.identity((loss_synthetic_domain + loss_real_domain)/2., name = 'total')
        with tf.variable_scope('defocus'):
            loss_defocus = 10 * tl.cost.mean_squared_error(output_synthetic_defocus, labels_synthetic_defocus, is_mean = True, name = 'synthetic')
        with tf.variable_scope('binary'):
            loss_synthetic_binary = tl.cost.sigmoid_cross_entropy(output_synthetic_binary_logits, labels_synthetic_binary, name = 'synthetic')
            loss_real_binary = tl.cost.sigmoid_cross_entropy(output_real_binary_logits, labels_real_binary, name = 'real')
            loss_binary = tf.identity((loss_synthetic_binary + loss_real_binary)/2., name = 'total')

        with tf.variable_scope('total_variation'):
            tv_loss_synthetic = lambda_tv * tf.reduce_sum(tf.image.total_variation(output_synthetic_defocus))
            tv_loss_real = lambda_tv * tf.reduce_sum(tf.image.total_variation(output_real_defocus))
            tv_loss = (tv_loss_real + tv_loss_synthetic) / 2.

        loss = tf.identity(loss_defocus + loss_binary + loss_domain + tv_loss, name = 'total')
        loss_init = tf.identity(loss_defocus + tv_loss_synthetic + loss_synthetic_binary, name = 'loss_init')

    ## DEFINE OPTIMIZER
    # variables to save / train
    t_vars = tl.layers.get_variables_with_name('defocus_net', True, False)
    a_vars = tl.layers.get_variables_with_name('unet', False, False)

    # define optimizer
    with tf.variable_scope('Optimizer'):
        lr_v = tf.Variable(lr_init, trainable = False)
        optim = tf.train.AdamOptimizer(lr_v, beta1 = beta1).minimize(loss, var_list = t_vars)
        optim_init = tf.train.AdamOptimizer(lr_v, beta1 = beta1).minimize(loss_init, var_list = a_vars)

    ## DEFINE SUMMARY
    # writer
    writer_scalar = tf.summary.FileWriter(log_dir, sess.graph, filename_suffix = '.loss_log')
    writer_image = tf.summary.FileWriter(log_dir, sess.graph, filename_suffix = '.image_log')
    if tl.global_flag['is_pretrain'] is True:
        writer_scalar_init = tf.summary.FileWriter(log_dir, sess.graph, filename_suffix = '.loss_log_init')
        writer_image_init = tf.summary.FileWriter(log_dir, sess.graph, filename_suffix = '.image_log_init')
    # summaries
    # for pretrain
    loss_sum_list_init = []
    with tf.variable_scope('loss_init'):
        loss_sum_list_init.append(tf.summary.scalar('1_total_loss_init', loss_init))
        loss_sum_list_init.append(tf.summary.scalar('2_defocus_loss_init', loss_defocus))
        loss_sum_list_init.append(tf.summary.scalar('3_binary_loss_init', loss_synthetic_binary))
        loss_sum_list_init.append(tf.summary.scalar('4_tv_loss_init', tv_loss_synthetic))
        loss_sum_init = tf.summary.merge(loss_sum_list_init)

    image_sum_list_init = []
    image_sum_list_init.append(tf.summary.image('1_synthetic_input_init', patches_synthetic))
    image_sum_list_init.append(tf.summary.image('2_synthetic_defocus_out_init', output_synthetic_defocus))
    image_sum_list_init.append(tf.summary.image('3_synthetic_defocus_gt_init', labels_synthetic_defocus))
    image_sum_list_init.append(tf.summary.image('4_synthetic_binary_out_init', output_synthetic_binary))
    image_sum_list_init.append(tf.summary.image('5_synthetic_binary_gt_init', labels_synthetic_binary))
    image_sum_init = tf.summary.merge(image_sum_list_init)

    # for train
    loss_sum_list = []
    with tf.variable_scope('loss'):
        loss_sum_list.append(tf.summary.scalar('1_total_loss', loss))
        loss_sum_list.append(tf.summary.scalar('2_domain_loss', loss_domain))
        loss_sum_list.append(tf.summary.scalar('3_defocus_loss', loss_defocus))
        loss_sum_list.append(tf.summary.scalar('4_binary_loss', loss_binary))
        loss_sum_list.append(tf.summary.scalar('5_tv_loss', tv_loss))
        loss_sum = tf.summary.merge(loss_sum_list)

    image_sum_list = []
    image_sum_list.append(tf.summary.image('1_synthetic_input', patches_synthetic))
    image_sum_list.append(tf.summary.image('2_synthetic_defocus_out', output_synthetic_defocus))
    image_sum_list.append(tf.summary.image('3_synthetic_defocus_gt', labels_synthetic_defocus))
    image_sum_list.append(tf.summary.image('4_synthetic_binary_out', output_synthetic_binary))
    image_sum_list.append(tf.summary.image('5_synthetic_binary_gt', labels_synthetic_binary))
    image_sum_list.append(tf.summary.image('6_real_input', patches_real))
    image_sum_list.append(tf.summary.image('7_real_defocus_out', output_real_defocus))
    image_sum_list.append(tf.summary.image('8_real_binary_out', output_real_binary))
    image_sum_list.append(tf.summary.image('9_real_binary_gt', labels_real_binary))
    image_sum = tf.summary.merge(image_sum_list)

    ## INITIALIZE SESSION
    tl.layers.initialize_global_variables(sess)
    if tl.files.load_and_assign_npz_dict(name = init_dir + '/{}_init.npz'.format(tl.global_flag['mode']), sess = sess) is False or tl.global_flag['is_pretrain']:
        print '*****************************************'
        print '           PRE-TRAINING START'
        print '*****************************************'
        global_step = 0
        for epoch in range(0, n_epoch_init + 1):
            total_loss_init, n_iter = 0, 0
            # shuffle datasets
            shuffle_index = np.arange(len(train_synthetic_img_list))
            np.random.shuffle(shuffle_index)

            train_synthetic_img_list = train_synthetic_img_list[shuffle_index]
            train_defocus_map_list = train_defocus_map_list[shuffle_index]
            train_synthetic_binary_map_list = train_synthetic_binary_map_list[shuffle_index]

            epoch_time = time.time()
            for idx in range(0, len(train_synthetic_img_list), batch_size_init):
                step_time = time.time()
                ## READ DATA
                # read synthetic data
                b_idx = (idx + np.arange(batch_size_init)) % len(train_synthetic_img_list)
                synthetic_images_blur = read_all_imgs(train_synthetic_img_list[b_idx], path = config.TRAIN.synthetic_img_path, n_threads = batch_size_init, mode = 'RGB')
                defocus_maps = read_all_imgs(train_defocus_map_list[b_idx], path = config.TRAIN.defocus_map_path, n_threads = batch_size_init, mode = 'GRAY')
                synthetic_binary_maps = read_all_imgs(train_synthetic_binary_map_list[b_idx], path = config.TRAIN.synthetic_binary_map_path, n_threads = batch_size_init, mode = 'GRAY')

                concatenated_images = np.concatenate((synthetic_images_blur, defocus_maps, synthetic_binary_maps), axis = 3)
                images = tl.prepro.crop_multi(concatenated_images, wrg = h, hrg = w, is_random = True)
                synthetic_images_blur = images[:, :, :, 0:3]
                synthetic_defocus_maps = np.expand_dims(images[:, :, :, 3], axis = 3)
                synthetic_binary_maps = np.expand_dims(images[:, :, :, 4], axis = 3)

                err_init, synthetic_defocus_out, synthetic_binary_out, lr, summary_loss_init, summary_image_init, _ = \
                sess.run([loss_init, output_synthetic_defocus, output_synthetic_binary, lr_v, loss_sum_init, image_sum_init, optim_init], {
                    patches_synthetic: synthetic_images_blur,
                    labels_synthetic_defocus: synthetic_defocus_maps,
                    labels_synthetic_binary: synthetic_binary_maps,
                    })

                print('[%s] Ep [%2d/%2d] %4d/%4d time: %4.2fs, err_init: %.3f, lr: %.8f' % \
                    (tl.global_flag['mode'], epoch, n_epoch_init, n_iter, len(train_synthetic_img_list)/batch_size_init, time.time() - step_time, err_init, lr))

                if global_step % config.TRAIN.write_log_every == 0:
                    writer_scalar_init.add_summary(summary_loss_init, global_step)
                    writer_image_init.add_summary(summary_image_init, global_step)

                total_loss_init += err_init
                n_iter += 1
                global_step += 1

            if epoch != config.TRAIN.n_epoch_init and epoch % config.TRAIN.refresh_image_log_every == 0:
                writer_image_init.close()
                remove_file_end_with(log_dir, '*.image_log_init')
                writer_image_init.reopen()
        tl.files.save_npz_dict(a_vars, name = init_dir + '/{}_init.npz'.format(tl.global_flag['mode']), sess = sess)
    writer_image_init.close()
    writer_scalar_init.close()

    ## START TRAINING
    print '*****************************************'
    print '             TRAINING START'
    print '*****************************************'
    global_step = 0
    for epoch in range(0, n_epoch + 1):
        total_loss, n_iter = 0, 0
        
        # shuffle datasets
        shuffle_index = np.arange(len(train_synthetic_img_list))
        np.random.shuffle(shuffle_index)

        train_synthetic_img_list = train_synthetic_img_list[shuffle_index]
        train_defocus_map_list = train_defocus_map_list[shuffle_index]
        train_synthetic_binary_map_list = train_synthetic_binary_map_list[shuffle_index]
        
        shuffle_index = np.arange(len(train_real_img_list))
        np.random.shuffle(shuffle_index)
        train_real_img_list = train_real_img_list[shuffle_index]
        train_real_binary_map_list = train_real_binary_map_list[shuffle_index]

        # update learning rate
        if epoch != 0 and (epoch % decay_every == 0):
            new_lr_decay = lr_decay ** (epoch // decay_every)
            sess.run(tf.assign(lr_v, lr_init * new_lr_decay))
        elif epoch == 0:
            sess.run(tf.assign(lr_v, lr_init))

        epoch_time = time.time()
        for idx in range(0, len(train_synthetic_img_list), batch_size):
            step_time = time.time()
            
            ## READ DATA
            # read synthetic data
            b_idx = (idx + np.arange(batch_size)) % len(train_synthetic_img_list)
            synthetic_images_blur = read_all_imgs(train_synthetic_img_list[b_idx], path = config.TRAIN.synthetic_img_path, n_threads = batch_size, mode = 'RGB')
            defocus_maps = read_all_imgs(train_defocus_map_list[b_idx], path = config.TRAIN.defocus_map_path, n_threads = batch_size, mode = 'GRAY')
            synthetic_binary_maps = read_all_imgs(train_synthetic_binary_map_list[b_idx], path = config.TRAIN.synthetic_binary_map_path, n_threads = batch_size, mode = 'GRAY')

            concatenated_images = np.concatenate((synthetic_images_blur, defocus_maps, synthetic_binary_maps), axis = 3)
            images = tl.prepro.crop_multi(concatenated_images, wrg = h, hrg = w, is_random = True)
            synthetic_images_blur = images[:, :, :, 0:3]
            synthetic_defocus_maps = np.expand_dims(images[:, :, :, 3], axis = 3)
            synthetic_binary_maps = np.expand_dims(images[:, :, :, 4], axis = 3)

            # read real data #
            b_idx = (idx % len(train_real_img_list) + np.arange(batch_size)) % len(train_real_img_list)
            images_blur = read_all_imgs(train_real_img_list[b_idx], path = config.TRAIN.real_img_path, n_threads = batch_size, mode = 'RGB')
            binary_maps = read_all_imgs(train_real_binary_map_list[b_idx], path = config.TRAIN.real_binary_map_path, n_threads = batch_size, mode = 'GRAY')
            real_images_blur, real_binary_maps = crop_pair_with_different_shape_images(images_blur, binary_maps, [h, w])

            ## RUN NETWORK
            err, err_d, err_def, err_bin, synthetic_defocus_out, synthetic_binary_out, real_defocus_out, real_binary_out, lr, summary_loss, summary_image, _ = \
            sess.run([loss, loss_domain, loss_defocus, loss_binary, output_synthetic_defocus, output_synthetic_binary, output_real_defocus, output_real_binary, lr_v, loss_sum, image_sum, optim], 
                {patches_synthetic: synthetic_images_blur,
                labels_synthetic_defocus: synthetic_defocus_maps,
                labels_synthetic_binary: synthetic_binary_maps,
                patches_real: real_images_blur,
                labels_real_binary: real_binary_maps,
                })
            
            print('[%s] Ep [%2d/%2d] %4d/%4d time: %4.2fs, err_tot: %.3f, err_dom: %.3f, err_def: %.3f, err_bin: %.3f, lr: %.8f' % \
                (tl.global_flag['mode'], epoch, n_epoch, n_iter, len(train_synthetic_img_list)/batch_size, time.time() - step_time, err, err_d, err_def, err_bin, lr))
            
            ## SAVE LOGS
            # save loss & image log
            if global_step % config.TRAIN.write_log_every == 0:
                writer_scalar.add_summary(summary_loss, global_step)
                writer_image.add_summary(summary_image, global_step)
            # save checkpoint
            if global_step % config.TRAIN.write_ckpt_every == 0:
                shutil.rmtree(ckpt_dir, ignore_errors = True)
                tl.files.save_ckpt(sess = sess, mode_name = '{}.ckpt'.format(tl.global_flag['mode']), save_dir = ckpt_dir, var_list = a_vars, global_step = global_step, printable = False)
            # save samples
            #if global_step % config.TRAIN.write_sample_every == 0:
            if global_step % 5 == 0:
                save_images(synthetic_images_blur, [ni, ni], sample_dir + '/{}_{}_1_synthetic_input.png'.format(epoch, global_step))
                save_images(synthetic_defocus_out, [ni, ni], sample_dir + '/{}_{}_2_synthetic_defocus_out.png'.format(epoch, global_step))
                save_images(synthetic_defocus_maps, [ni, ni], sample_dir + '/{}_{}_3_synthetic_defocus_gt.png'.format(epoch, global_step))
                save_images(synthetic_binary_out, [ni, ni], sample_dir + '/{}_{}_4_synthetic_binary_out.png'.format(epoch, global_step))
                save_images(synthetic_binary_maps, [ni, ni], sample_dir + '/{}_{}_5_synthetic_binary_gt.png'.format(epoch, global_step))
                save_images(real_images_blur, [ni, ni], sample_dir + '/{}_{}_6_real_input.png'.format(epoch, global_step))
                save_images(real_defocus_out, [ni, ni], sample_dir + '/{}_{}_7_real_defocus_out.png'.format(epoch, global_step))
                save_images(real_binary_out, [ni, ni], sample_dir + '/{}_{}_8_real_binary_out.png'.format(epoch, global_step))
                save_images(real_binary_maps, [ni, ni], sample_dir + '/{}_{}_9_real_binary_gt.png'.format(epoch, global_step))

            total_loss += err
            n_iter += 1
            global_step += 1
            
        print('[*] Epoch: [%2d/%2d] time: %4.4fs, total_err: %.8f' % (epoch, n_epoch, time.time() - epoch_time, total_loss/n_iter))
        # reset image log
        if epoch % config.TRAIN.refresh_image_log_every == 0:
            writer_image.close()
            remove_file_end_with(log_dir, '*.image_log')
            writer_image.reopen()

def evaluate():
    print 'Evaluation Start'
    date = datetime.datetime.now().strftime('%Y_%m_%d/%H-%M')
    # directories
    mode_dir = config.TRAIN.root_dir + '{}'.format(tl.global_flag['mode'])
    ckpt_dir = mode_dir + '/checkpoint'
    sample_dir = mode_dir + '/samples/1_test/{}'.format(date)
    
    # input
    test_blur_img_list = np.array(sorted(tl.files.load_file_list(path = config.TEST.real_img_path, regx = '.*', printable = False)))
    test_gt_list = np.array(sorted(tl.files.load_file_list(path = config.TEST.real_binary_map_path, regx = '.*', printable = False)))
    
    test_blur_imgs = read_all_imgs(test_blur_img_list, path = config.TEST.real_img_path, n_threads = len(test_blur_img_list), mode = 'RGB')
    test_gt_imgs = read_all_imgs(test_gt_list, path = config.TEST.real_binary_map_path, n_threads = len(test_gt_list), mode = 'GRAY')
    
    reuse = False
    for i in np.arange(len(test_blur_imgs)):
        test_blur_img = np.copy(test_blur_imgs[i])
        test_blur_img = refine_image(test_blur_img)
        shape = test_blur_img.shape

        patches_blurred = tf.placeholder('float32', [1, shape[0], shape[1], 3], name = 'input_patches')
        # define model
        with tf.variable_scope('defocus_net') as scope:
            with tf.variable_scope('unet') as scope:
                with tf.variable_scope('unet_down') as scope:
                    f0, f1_2, f2_3, f3_4, final_feature = UNet_down(patches_blurred, is_train = False, reuse = reuse, scope = scope)
                with tf.variable_scope('binary_net') as scope:
                    with tf.variable_scope('unet_up_defocus_map') as scope:
                        _, output_defocus = UNet_up(f0, f1_2, f2_3, f3_4, final_feature, shape[0], shape[1], is_train = False, reuse = reuse, scope = scope)

                _, output_binary = Binary_Net(output_defocus, is_train = False, reuse = reuse, scope = scope)
                        
        a_vars = tl.layers.get_variables_with_name('unet', False, False)

        # init session
        sess = tf.Session(config = tf.ConfigProto(allow_soft_placement = True, log_device_placement = False))
        tl.layers.initialize_global_variables(sess)

        # load checkpoint
        tl.files.load_ckpt(sess = sess, mode_name = '{}.ckpt'.format(tl.global_flag['mode']), save_dir = ckpt_dir, var_list = a_vars)

        # run network
        print 'processing {} ...'.format(test_blur_img_list[i])
        processing_time = time.time()
        defocus_map, binary_map = sess.run([output_defocus, output_binary], {patches_blurred: np.expand_dims(test_blur_img, axis = 0)})
        defocus_map = np.squeeze(defocus_map)
        defocus_map_norm = defocus_map - defocus_map.min()
        defocus_map_norm = defocus_map_norm / defocus_map_norm.max()
        binary_map = np.squeeze(binary_map)
        print 'processing {} ... Done [{:.3f}s]'.format(test_blur_img_list[i], time.time() - processing_time)
        
        tl.files.exists_or_mkdir(sample_dir, verbose = False)
        scipy.misc.toimage(test_blur_img, cmin = 0., cmax = 1.).save(sample_dir + '/{}_1_input.png'.format(i))
        scipy.misc.toimage(defocus_map, cmin = 0., cmax = 1.).save(sample_dir + '/{}_2_defocus_map_out.png'.format(i))
        scipy.misc.toimage(defocus_map_norm, cmin = 0., cmax = 1.).save(sample_dir + '/{}_3_defocus_map_norm_out.png'.format(i))
        scipy.misc.toimage(binary_map, cmin = 0., cmax = 1.).save(sample_dir + '/{}_4_binary_map_out.png'.format(i))
        scipy.misc.toimage(np.squeeze(test_gt_imgs[i]), cmin = 0., cmax = 1.).save(sample_dir + '/{}_5_binary_map_gt.png'.format(i))

        sess.close()
        reuse = True

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()

    parser.add_argument('--mode', type = str, default = 'sharp_ass', help = 'model name')
    parser.add_argument('--is_train', type = str , default = 'true', help = 'whether to train or not')
    parser.add_argument('--is_pretrain', type = str , default = 'false', help = 'whether to pretrain or not')
    parser.add_argument('--delete_log', type = str , default = 'false', help = 'whether to delete log or not')

    args = parser.parse_args()

    tl.global_flag['mode'] = args.mode
    tl.global_flag['is_train'] = t_or_f(args.is_train)
    tl.global_flag['is_pretrain'] = t_or_f(args.is_pretrain)
    tl.global_flag['delete_log'] = t_or_f(args.delete_log)
    

    if tl.global_flag['is_train']:
        train()
    else:
        evaluate()
